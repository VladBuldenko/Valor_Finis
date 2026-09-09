import logging

from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.db.database_models import import_database_models
from app.modules.analytics.analytics_router import router as analytics_router
from app.modules.budgets.budget_router import router as budgets_router
from app.modules.categories.router import router as categories_router
from app.modules.expenses.expenses_router import router as expenses_router
from app.modules.goals.goal_router import router as goals_router
from app.modules.receipts.receipt_router import router as receipts_router


# Configures logging for this application's own modules (the "app.*"
# logger namespace used by every `logging.getLogger(__name__)` call in
# this codebase) so INFO-level diagnostic logs are actually emitted.
#
# Without this, Python's logging module has no configured handler
# anywhere in the chain, so it falls back to `logging.lastResort`, which
# itself only emits WARNING and above -- INFO-level calls (e.g. receipt
# OCR timing telemetry) are silently dropped even though the call site
# looks correct. This was confirmed directly: with no logging
# configuration, `logging.getLogger("app...").getEffectiveLevel()` is
# WARNING (30), not INFO (20).
#
# Scoped to the "app" logger (not the root logger), so third-party
# library logging (uvicorn, httpx, PIL, etc.) is unaffected and keeps
# its own defaults. Propagation to the root logger is left enabled
# (the default) rather than disabled: this application currently
# attaches no handler to the root logger, so nothing else emits these
# records a second time, and leaving propagation on is what lets
# pytest's `caplog` fixture (which attaches its own handler to the root
# logger) continue to capture these logs in tests.
#
# The `if not _app_logger.handlers` guard makes this idempotent: a
# normal Python process only executes this module's top-level code
# once (imports are cached in sys.modules), but this still protects
# against duplicate log lines if `app.main` is ever re-imported/
# re-executed within the same process (e.g. an explicit module reload,
# or test tooling that re-runs module-level code) -- without it, each
# execution would add another StreamHandler and every subsequent log
# call would be printed once per accumulated handler.
_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
if not _app_logger.handlers:
    _app_log_handler = logging.StreamHandler()
    _app_log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    _app_logger.addHandler(_app_log_handler)


import_database_models()


app = FastAPI(
    title="Valor API",
    description="Backend API for Valor personal finance application.",
    version="0.1.0",
)


register_exception_handlers(app)


app.include_router(
    expenses_router,
    prefix="/api/v1",
)
app.include_router(
    receipts_router,
    prefix="/api/v1",
)
app.include_router(
    categories_router,
    prefix="/api/v1",
)
app.include_router(
    budgets_router,
    prefix="/api/v1",
)
app.include_router(
    goals_router,
    prefix="/api/v1",
)
app.include_router(
    analytics_router,
    prefix="/api/v1",
)


# Returns basic API information.
# This function exists to provide a simple root endpoint
# instead of returning HTTP 404.
# Parameters:
# - None.
# Returns:
# - Basic API metadata and useful documentation links.
@app.get(
    "/",
    tags=["System"],
)
def root() -> dict[str, str]:
    return {
        "service": "Valor API",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


# Checks if the backend service is running.
# This function exists to verify that the API is alive and reachable.
# Parameters:
# - None.
# Returns:
# - Basic service status information.
@app.get(
    "/health",
    tags=["System"],
)
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "valor-api",
        "version": "0.1.0",
    }