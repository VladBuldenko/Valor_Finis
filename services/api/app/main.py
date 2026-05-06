from fastapi import FastAPI

app = FastAPI(
    title="Valor API",
    description="Backend API for Valor personal finance application.",
    version="0.1.0",
)


@app.get("/health", tags=["System"])
def health_check():
    """
    Health check endpoint.

    Used to verify that the backend service is running.
    """
    return {
        "status": "ok",
        "service": "valor-api",
        "version": "0.1.0",
    }