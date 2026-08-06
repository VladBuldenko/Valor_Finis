from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.db.database_models import import_database_models
from app.modules.analytics.analytics_router import router as analytics_router
from app.modules.budgets.budget_router import router as budgets_router
from app.modules.categories.router import router as categories_router
from app.modules.expenses.expenses_router import router as expenses_router
from app.modules.goals.goal_router import router as goals_router
from app.modules.receipts.receipt_router import router as receipts_router


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