import pytest
from unittest.mock import Mock, patch


def test_health_endpoint(test_client):
    response = test_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"