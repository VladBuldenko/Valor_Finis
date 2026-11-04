"""
Sanitized evidence records.

What:
    One JSON record per staging operation (success or refusal) listing the
    checks that ran and their result.

Why:
    QA-0 requires that nothing be claimed without evidence and that evidence
    never contain secrets. A record names the staging entry and database,
    fingerprints the host, and lists check names with pass/fail. It never
    holds a URL, host name, user name, password, key or raw tool output.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from staging_ops.redaction import fingerprint

TOOL = "staging_ops/1"


@dataclass
class EvidenceRecord:
    operation: str
    staging_id: Optional[str] = None
    database: Optional[str] = None
    host_fingerprint: Optional[str] = None
    database_oid: Optional[int] = None
    server_major: Optional[int] = None
    outcome: str = "REFUSED"
    code: Optional[str] = None
    steps: List[Dict[str, str]] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    # Records the result of one named check.
    def step(self, name: str, result: str = "pass") -> None:
        self.steps.append({"check": name, "result": result})

    def describe_target(self, configured) -> None:
        self.staging_id = configured.staging_id
        self.database = configured.database
        self.host_fingerprint = fingerprint("db-host", f"{configured.host}:{configured.port}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": TOOL,
            "operation": self.operation,
            "outcome": self.outcome,
            "code": self.code,
            "staging_id": self.staging_id,
            "database": self.database,
            "host_fingerprint": self.host_fingerprint,
            "database_oid": self.database_oid,
            "server_major": self.server_major,
            "steps": self.steps,
            "details": self.details,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# Current UTC time as an ISO 8601 string (second precision).
def utc_now(clock=None) -> str:
    moment = clock() if clock else datetime.now(timezone.utc)

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Writes the record as JSON into a directory the caller chose.
# The file name is derived from the operation and the start time, and an
# existing file is never overwritten.
# Parameters:
# - directory: target directory (created if missing).
# - record: the record to store.
# Returns:
# - Path of the written file.
def write_evidence(directory: str, record: EvidenceRecord) -> str:
    os.makedirs(directory, exist_ok=True)
    stamp = record.started_at.replace(":", "").replace("-", "") or "unknown"

    for sequence in range(1, 100):
        path = os.path.join(directory, f"{record.operation}-{stamp}-{sequence:02d}.json")

        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue

        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")

        return path

    raise FileExistsError("too many evidence files with the same timestamp")
