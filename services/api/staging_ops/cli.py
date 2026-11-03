"""
Command line for the staging tooling.

    python -m staging_ops identify  --environment staging --staging STG-1 --approved-targets FILE
    python -m staging_ops bootstrap --environment staging --staging STG-1 --approved-targets FILE --evidence-dir DIR
    python -m staging_ops reset     --environment staging --staging STG-1 --approved-targets FILE --evidence-dir DIR
    python -m staging_ops seed      --environment staging --staging STG-1 --approved-targets FILE --evidence-dir DIR --users-file FILE [--as-of YYYY-MM-DD]

What:
    Thin wiring: it reads the credentials from the process environment (never
    from arguments), loads the approved targets, and calls the guarded
    operation. There is no force, yes or skip flag.

Exit status: 0 done; 11 refused before any change; 12 failed after a change
began (see the evidence record); 64 usage error.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Callable, List, Mapping, Optional

from staging_ops.bootstrap import bootstrap, verify_target
from staging_ops.errors import StagingRefused
from staging_ops.evidence import EvidenceRecord, utc_now, write_evidence
from staging_ops.identity import DatabaseFacts
from staging_ops.operations import Operations, real_operations
from staging_ops.reset import interactive_confirm, reset
from staging_ops.seed import seed
from staging_ops.target_config import load_approved_targets

EXIT_OK = 0
EXIT_REFUSED = 11
EXIT_FAILED = 12
EXIT_USAGE = 64


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="staging_ops", description="Guarded staging bootstrap, reset and seed.")
    parser.add_argument("command", choices=["identify", "bootstrap", "reset", "seed"])
    parser.add_argument("--environment", default=None, help="must be exactly 'staging'")
    parser.add_argument("--staging", default=None, help="approved staging entry id, for example STG-1")
    parser.add_argument("--approved-targets", required=True, help="operator-held approved-targets JSON, stored outside the repository")
    parser.add_argument("--evidence-dir", default=None, help="directory for the sanitized evidence record")
    parser.add_argument("--users-file", default=None, help="seed only: JSON mapping QA-A and QA-B to staging Auth user ids")
    parser.add_argument("--as-of", default=None, help="seed only: business date (default: today, UTC)")

    return parser


def _identify(args, environ: Mapping[str, str], approved, operations: Operations, say: Callable[[str], None]) -> EvidenceRecord:
    record = EvidenceRecord(operation="identify", started_at=utc_now())

    try:
        configured, verified, facts = verify_target(args.environment, args.staging, environ, approved, operations, record, require_oid=False)
        state = "empty-and-unmigrated" if facts.alembic_revisions is None and not facts.unexpected_objects else "contains-schema-objects"
        record.details.update({"database_state": state, "oid_matches_approved": configured.oid == verified.oid if configured.oid else "not-pinned"})
        record.outcome = "OK"
        say(
            f"staging entry: {configured.staging_id}\n"
            f"database: {configured.database}\n"
            f"database oid (owner records this in the approved targets): {verified.oid}\n"
            f"server major version: {verified.server_version_num // 10000}\n"
            f"database state: {state}"
        )
    except StagingRefused as error:
        record.code = error.code
        raise
    finally:
        record.finished_at = utc_now()

        if args.evidence_dir:
            write_evidence(args.evidence_dir, record)

    return record


# Runs one command. Returns the process exit status.
# Parameters:
# - argv: command line (without the program name).
# - environ: environment mapping (defaults to a copy of os.environ).
# - operations: injected capabilities (defaults to the real ones).
def main(
    argv: Optional[List[str]] = None,
    environ: Optional[Mapping[str, str]] = None,
    operations: Optional[Operations] = None,
    confirm: Optional[Callable[[str], str]] = None,
    say: Callable[[str], None] = print,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    # The app settings module loads a .env file on import; a stray file must never
    # supply a value the validated environment did not.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    environ = dict(os.environ if environ is None else environ)

    if args.command != "identify" and not args.evidence_dir:
        print("REFUSED [USAGE]: --evidence-dir is required for a mutating command", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "seed" and not args.users_file:
        print("REFUSED [USAGE]: --users-file is required for seed", file=sys.stderr)
        return EXIT_USAGE

    try:
        approved = load_approved_targets(args.approved_targets)
        operations = operations or real_operations()

        if args.command == "identify":
            _identify(args, environ, approved, operations, say)
        elif args.command == "bootstrap":
            bootstrap(args.environment, args.staging, environ, approved, operations, args.evidence_dir, say)
        elif args.command == "reset":
            reset(args.environment, args.staging, environ, approved, operations, confirm or interactive_confirm, args.evidence_dir, say)
        else:
            try:
                with open(args.users_file, encoding="utf-8") as handle:
                    users = json.load(handle)
                as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
            except (OSError, ValueError):
                raise StagingRefused("USAGE", "the users file or --as-of is unreadable or malformed") from None

            seed(args.environment, args.staging, environ, approved, operations, users, as_of, args.evidence_dir, say)
    except StagingRefused as error:
        print(f"REFUSED [{error.code}]: {error.message}", file=sys.stderr)

        return EXIT_FAILED if error.mutated else EXIT_REFUSED

    say("OK")

    return EXIT_OK

