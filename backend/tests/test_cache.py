import pytest
from unittest.mock import Mock, patch
from app.services.cache import set_cached_result, get_cached_result


@patch('app.services.cache.get_redis_client')
def test_set_cached_result(mock_redis):
    mock_client = Mock()
    mock_redis.return_value = mock_client
    
    test_data = {"job_id": "test_123", "status": "completed"}
    
    set_cached_result("test_123", test_data, ttl_sec=3600)
    
    mock_client.setex.assert_called_once()
    args = mock_client.setex.call_args[0]
    assert "result:test_123" in args[0]
    # Third parameter should be TTL
    assert args[1] == 3600


@patch('app.services.cache.get_redis_client')
def test_get_cached_result_exists(mock_redis):
    mock_client = Mock()
    mock_client.get.return_value = '{"job_id": "test_123", "status": "completed"}'
    mock_redis.return_value = mock_client
    
    result = get_cached_result("test_123")
    
    assert result is not None
    assert result["job_id"] == "test_123"
    assert result["status"] == "completed"


@patch('app.services.cache.get_redis_client')
def test_get_cached_result_not_exists(mock_redis):
    mock_client = Mock()
    mock_client.get.return_value = None
    mock_redis.return_value = mock_client
    
    result = get_cached_result("test_123")
    
    assert result is None