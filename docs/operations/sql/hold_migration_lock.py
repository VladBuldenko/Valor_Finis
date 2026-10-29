"""Holds the guarded-migration advisory lock for the lifetime of the runner (VF-OPS03-1 SR-04, SR-07).

Started in the background by run_guarded_migration.sh with the same DATABASE_URL Alembic uses. It takes ONE session-level
`pg_try_advisory_lock(7165, 1)` (never waits), reports LOCKED, BUSY or ERROR in the status file given as argument, and then
keeps the connection open. The lock is released by PostgreSQL itself when the connection closes, so nothing can stay held.

Lifetime (SR-07): there is NO time cap. The holder lives exactly as long as its parent (the runner): it exits when the parent
disappears (also after SIGKILL of the runner) or on SIGTERM, so a long migration can never outlive its lock.

Loss detection (SR-07): about once a second it asks the server whether THIS backend still holds the lock
(`pg_locks` row for this `pg_backend_pid()`). If the connection was cut, the backend was terminated, or the lock is not held by the
backend that answers (which is what happens behind a transaction-mode pooler such as pgbouncer, where consecutive statements
may run on different server backends), it exits with status 2. The runner watches the holder and terminates the upgrade (a
single transaction, so it rolls back) instead of continuing without a lock. The connection runs in autocommit mode, so it is
an idle session, never idle-in-transaction (which the read-only preflight would rightly refuse).
"""
import os
import signal
import sys
import time

from sqlalchemy import create_engine, text

LOCK_CLASS, LOCK_OBJECT = 7165, 1
HELD = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND classid = :a AND objid = :b AND objsubid = 2 "
    "AND pid = pg_backend_pid() AND granted)"
)


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
        arguments = {"a": LOCK_CLASS, "b": LOCK_OBJECT}
        if not connection.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), arguments).scalar():
            report(status, "BUSY")
            return
        # A separate statement: behind a transaction pooler this one may land on another backend and not see the lock.
        if not connection.execute(HELD, arguments).scalar():
            report(status, "ERROR")
            sys.exit(2)
        report(status, "LOCKED")
        last_check = time.time()
        while os.getppid() == parent:
            time.sleep(0.3)
            if time.time() - last_check >= 1.0:
                last_check = time.time()
                if not connection.execute(HELD, arguments).scalar():
                    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fixed outcome only: no exception text (it can contain connection details). Any loss of the connection ends here.
        try:
            if not os.path.exists(sys.argv[1]):
                report(sys.argv[1], "ERROR")
        except Exception:
            pass
        sys.exit(2)
