from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


# Tests that the health endpoint is available.
# This test exists to verify that the API service is running correctly.
# Parameters:
# - None.
# Returns:
# - None. The test passes if the response status code and body are correct.
def test_health_check_returns_service_status() -> None:
    # Arrange
    expected_response = {
        "status": "ok",
        "service": "valor-api",
        "version": "0.1.0",
    }

    # Act
    response = client.get("/health")

    # Assert
    assert response.status_code == 200
    assert response.json() == expected_response