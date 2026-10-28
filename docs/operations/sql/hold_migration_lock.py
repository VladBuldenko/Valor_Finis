"""Holds the guarded-migration advisory lock for the lifetime of the runner (VF-OPS03-1 SR-04).

Started in the background by run_guarded_migration.sh with the same DATABASE_URL Alembic uses. It takes ONE session-level
`pg_try_advisory_lock(7165, 1)` (never waits), reports LOCKED or BUSY in the status file given as argument, and then only
keeps the connection open. The lock is released by PostgreSQL itself when the connection closes, so nothing can stay held:
the holder exits (closing the connection) when its parent process disappears, on SIGTERM, or after a hard 15-minute cap.
The connection runs in autocommit mode, so it is an idle session, never an idle-in-transaction one (which the read-only
preflight would rightly refuse).
"""
import os
import signal
import sys
import time

from sqlalchemy import create_engine, text

LOCK_CLASS, LOCK_OBJECT, MAX_SECONDS = 7165, 1, 900


def report(path, word):
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        handle.write(word)
    os.replace(temporary, path)


def main():
    status = sys.argv[1]
    parent = os.getppid()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = connection.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": LOCK_CLASS, "b": LOCK_OBJECT}).scalar()
        report(status, "LOCKED" if acquired else "BUSY")
        if not acquired:
            return
        started = time.time()
        while os.getppid() == parent and time.time() - started < MAX_SECONDS:
            time.sleep(0.3)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fixed outcome only: no exception text (it can contain connection details).
        try:
            report(sys.argv[1], "ERROR")
        except Exception:
            pass
        sys.exit(1)
