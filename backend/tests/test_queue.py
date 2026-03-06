import pytest
from unittest.mock import Mock, patch
from app.services.queue import push_job, pop_job


@patch('app.services.queue.get_redis_client')
def test_push_job_success(mock_redis):
    mock_client = Mock()
    mock_client.llen.return_value = 5
    mock_client.lpush.return_value = 1
    mock_redis.return_value = mock_client

    result = push_job("test_job_123")

    assert result is True
    mock_client.llen.assert_called_once()
    mock_client.lpush.assert_called_once()


@patch('app.services.queue.get_redis_client')
def test_push_job_queue_full(mock_redis):
    mock_client = Mock()
    mock_client.llen.return_value = 1000  # MAX_QUEUE_SIZE
    mock_redis.return_value = mock_client

    result = push_job("test_job_123")

    assert result is False
    mock_client.lpush.assert_not_called()


@patch('app.services.queue.get_redis_client')
def test_pop_job_success(mock_redis):
    mock_client = Mock()
    mock_client.brpop.return_value = ("lumen_jobs", "test_job_123")
    mock_redis.return_value = mock_client

    result = pop_job(block_timeout=5)

    assert result == "test_job_123"
    mock_client.brpop.assert_called_once()


@patch('app.services.queue.get_redis_client')
def test_pop_job_empty(mock_redis):
    mock_client = Mock()
    mock_client.brpop.return_value = None
    mock_redis.return_value = mock_client

    result = pop_job()

    assert result is None


@patch('app.services.queue.get_redis_client')
def test_push_job_redis_error(mock_redis):
    mock_redis.side_effect = Exception("Redis connection failed")

    result = push_job("test_job_123")

    assert result is False


@patch('app.services.queue.get_redis_client')
def test_pop_job_redis_error(mock_redis):
    mock_redis.side_effect = Exception("Redis connection failed")

    result = pop_job()

    assert result is None
