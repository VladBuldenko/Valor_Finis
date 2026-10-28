"""Backup and restore evidence for the guarded migration runner (VF-OPS03-1).

Standard library only (Python 3.9 compatible). Three commands, used by shell scripts that never print their inputs:

  inspect-dump  <dump> <expected_db> <source_revision> <tables>
        Machine-verifies the dump itself and prints KEY=VALUE facts:
          * regular, private (no group/other bits), operator-owned, at least 4096 bytes, no symlink;
          * `pg_restore --list` header: the archive records the database it was taken from (`dbname`) and
            must equal <expected_db>; the server major version is recorded;
          * the archive DATA of alembic_version (read with `pg_restore --data-only`) must hold exactly
            <source_revision>: a dump of another database or another revision is rejected;
          * the required tables are listed.
  write-receipt <receipt_out> KEY=VALUE...
        Seals and writes a receipt (verifier-produced; see verify_backup_restore.sh).
  check-receipt <receipt> <target> <expected_db> <source_revision> <tables>
        Used by run_guarded_migration.sh: re-runs inspect-dump on the dump the receipt names and requires every
        receipt field to agree with it, plus the seal, the binding to this gate and the 24 h freshness rule.
        Prints DUMP_SERVER_MAJOR=<n> on success.

What the seal is and is not: RECEIPT_SEAL is a SHA-256 over the receipt fields and a fixed context string. It makes a
receipt that was typed by hand, edited, or copied between gates fail. It is NOT a cryptographic signature: anyone who
reads this file can recompute it, so it does not defend against a deliberately dishonest operator.
"""
import hashlib
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

MAX_AGE = 24 * 3600
SKEW = 300
MIN_DUMP_BYTES = 4096
SEAL_CONTEXT = "vf-backup-receipt-v2\n"
KEYS = (
    "RECEIPT_VERSION", "GATE_TARGET", "DATABASE", "SOURCE_REVISION", "DUMP_FILE", "DUMP_SHA256", "DUMP_DBNAME",
    "DUMP_SERVER_MAJOR", "DUMP_CREATED_AT_UTC", "RESTORE_DATABASE", "RESTORE_REVISION", "RESTORE_PREFLIGHT",
    "RESTORE_SERVER_MAJOR", "RESTORE_VERIFIED_AT_UTC", "RECEIPT_SEAL",
)
REVISION = re.compile(r"[0-9a-f]{12}")
STAMP = "%Y%m%dT%H%M%SZ"


def fail(reason):
    print(reason, file=sys.stderr)
    sys.exit(1)


def stamp(epoch):
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(STAMP)


def parse_stamp(value, name):
    try:
        return datetime.strptime(value, STAMP).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        fail("%s is not a UTC timestamp like 20261028T101500Z" % name)


def seal_of(fields):
    body = "\n".join("%s=%s" % (key, fields[key]) for key in sorted(fields) if key != "RECEIPT_SEAL")
    return hashlib.sha256((SEAL_CONTEXT + body).encode("utf-8")).hexdigest()


def private_file(path, what, private):
    try:
        info = os.lstat(path)
    except OSError:
        fail("%s is missing or unreadable" % what)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        fail("%s must be a regular file owned by the operator (no symlink)" % what)
    if info.st_mode & (0o077 if private else 0o022):
        fail("%s has unsafe permissions" % what)
    return info


def read_nofollow(path, mode):
    return os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), mode)


def inspect_dump(dump, expected_db, source_revision, tables):
    if not os.path.isabs(dump):
        fail("DUMP_FILE must be an absolute path")
    info = private_file(dump, "the dump file", True)
    if info.st_size < MIN_DUMP_BYTES:
        fail("the dump file is trivially small")
    now = time.time()
    if now - info.st_mtime > MAX_AGE or info.st_mtime > now + SKEW:
        fail("the dump file is not from the last 24 hours")
    digest = hashlib.sha256()
    with read_nofollow(dump, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)

    listing = subprocess.run(["pg_restore", "--list", dump], capture_output=True, text=True)
    if listing.returncode != 0:
        fail("pg_restore cannot read the dump file")
    header = listing.stdout.split("; Selected TOC Entries", 1)[0]
    named = re.search(r"^;\s+dbname: (\S+)\s*$", header, re.MULTILINE)
    version = re.search(r"^;\s+Dumped from database version: (\d+)", header, re.MULTILINE)
    if not named or not version:
        fail("the dump archive header does not record its source database and server version")
    if named.group(1) != expected_db:
        fail("the dump was not taken from the expected database")
    present = set(re.findall(r"\bTABLE public (\w+) ", listing.stdout))
    missing = [name for name in tables.split(",") if name not in present]
    if missing:
        fail("the dump does not list the required tables: " + ",".join(missing))

    data = subprocess.run(["pg_restore", "--data-only", "--table=alembic_version", "--file=-", dump],
                          capture_output=True, text=True)
    if data.returncode != 0:
        fail("pg_restore cannot read the alembic_version data of the dump")
    copied = re.search(r"^COPY public\.alembic_version \(version_num\) FROM stdin;\n(.*?)\n\\\.$", data.stdout,
                       re.MULTILINE | re.DOTALL)
    revisions = copied.group(1).split("\n") if copied and copied.group(1) else []
    if revisions != [source_revision]:
        fail("the dump holds a different alembic revision than the required source revision")
    return {
        "DUMP_SHA256": digest.hexdigest(), "DUMP_DBNAME": named.group(1), "DUMP_SERVER_MAJOR": version.group(1),
        "DUMP_CREATED_AT_UTC": stamp(info.st_mtime),
    }


def read_receipt(path):
    info = private_file(path, "the evidence receipt", False)
    if not 0 < info.st_size <= 4096:
        fail("the evidence receipt is empty or too large")
    fields = {}
    for line in read_nofollow(path, "r").read().splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in KEYS or key in fields or value != value.strip() or not value:
            fail("the evidence receipt has an unknown, duplicate or malformed line")
        fields[key] = value
    if sorted(fields) != sorted(KEYS):
        fail("the evidence receipt does not contain exactly the required fields")
    return fields


def check_receipt(path, target, expected_db, source_revision, tables):
    now = time.time()
    fields = read_receipt(path)
    if fields["RECEIPT_VERSION"] != "2" or seal_of(fields) != fields["RECEIPT_SEAL"]:
        fail("the receipt was not produced by verify_backup_restore.sh (seal mismatch)")
    if (fields["GATE_TARGET"], fields["DATABASE"], fields["SOURCE_REVISION"]) != (target, expected_db, source_revision):
        fail("the receipt is not bound to this target, database and source revision")
    if fields["DUMP_DBNAME"] != expected_db or fields["RESTORE_REVISION"] != source_revision:
        fail("the receipt does not record the expected database and revision")
    if fields["RESTORE_PREFLIGHT"] != "PASS":
        fail("the receipt does not record a PASSed restore preflight")
    restore_database = fields["RESTORE_DATABASE"]
    if not re.fullmatch(r"[A-Za-z0-9_]+_test", restore_database) or restore_database == expected_db:
        fail("the restore must have been verified on a throwaway *_test database, never the target")
    created = parse_stamp(fields["DUMP_CREATED_AT_UTC"], "DUMP_CREATED_AT_UTC")
    verified = parse_stamp(fields["RESTORE_VERIFIED_AT_UTC"], "RESTORE_VERIFIED_AT_UTC")
    if created > now + SKEW or verified > now + SKEW or verified < created:
        fail("the receipt timestamps are inconsistent")
    if now - created > MAX_AGE or now - verified > MAX_AGE:
        fail("the backup evidence is older than 24 hours: take and verify a fresh backup")

    facts = inspect_dump(fields["DUMP_FILE"], expected_db, source_revision, tables)
    for key, value in facts.items():
        if key == "DUMP_CREATED_AT_UTC":
            if abs(parse_stamp(value, key) - created) > 2:
                fail("the dump file changed after the receipt was written")
        elif fields[key] != value:
            fail("the dump no longer matches the receipt (%s)" % ("SHA-256" if key == "DUMP_SHA256" else key))
    print("DUMP_SERVER_MAJOR=" + fields["DUMP_SERVER_MAJOR"])


def write_receipt(path, assignments):
    fields = {}
    for assignment in assignments:
        key, _separator, value = assignment.partition("=")
        fields[key] = value
    fields["RECEIPT_VERSION"] = "2"
    fields["RECEIPT_SEAL"] = ""
    fields["RECEIPT_SEAL"] = seal_of(fields)
    if sorted(fields) != sorted(KEYS):
        fail("write-receipt needs exactly the receipt fields")
    temporary = "%s.tmp.%d" % (path, os.getpid())
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("".join("%s=%s\n" % (key, fields[key]) for key in KEYS))
    os.replace(temporary, path)


def main(argv):
    sys.excepthook = lambda *_: (print("unexpected error while handling the evidence", file=sys.stderr), os._exit(1))
    command = argv[1] if len(argv) > 1 else ""
    if command == "inspect-dump" and len(argv) == 6:
        for key, value in inspect_dump(*argv[2:6]).items():
            print("%s=%s" % (key, value))
    elif command == "check-receipt" and len(argv) == 7:
        check_receipt(*argv[2:7])
    elif command == "write-receipt" and len(argv) > 3:
        write_receipt(argv[2], argv[3:])
    else:
        fail("usage: backup_evidence.py inspect-dump|check-receipt|write-receipt ...")


if __name__ == "__main__":
    main(sys.argv)
