"""Shared test fixtures for FastAPI Radar tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_radar import Radar

from tortoise import Tortoise


@pytest.fixture(scope="function")
async def app():
    """Create a test FastAPI application."""
    return FastAPI(title="Test App")


@pytest.fixture(scope="function")
async def radar_app(app):
    """Create a FastAPI app with Radar configured."""
    # Initialize Radar
    radar = Radar(
        app,
        dashboard_path="/__radar",
        max_requests=100,
        retention_hours=24,
        slow_query_threshold=100,
    )

    # Initialize Tortoise for testing
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["fastapi_radar.models"]},
    )
    await Tortoise.generate_schemas()

    yield app, radar

    await Tortoise.close_connections()


@pytest.fixture(scope="function")
async def client(radar_app):
    """Create a test client for the Radar-enabled app."""
    app, radar = radar_app
    # TestClient is synchronous, but we need it for testing endpoints.
    # For async tests, we might want to use AsyncClient, but keeping TestClient for now
    # as it's standard for FastAPI tests unless we specifically need async client features.
    # However, since we are using Tortoise (async), we might need to handle async context.
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
async def db():
    """Initialize Tortoise DB for unit tests."""
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture(scope="function")
def simple_app():
    """Create a simple FastAPI app without Radar for isolated testing."""
    return FastAPI(title="Simple Test App")


@pytest.fixture
def sample_request_data():
    """Sample request data for testing."""
    return {
        "request_id": "test-request-123",
        "method": "GET",
        "url": "http://testserver/api/users",
        "path": "/api/users",
        "query_params": {"page": "1", "limit": "10"},
        "headers": {
            "user-agent": "test-client",
            "content-type": "application/json",
        },
        "body": '{"test": "data"}',
        "status_code": 200,
        "duration_ms": 45.67,
        "client_ip": "127.0.0.1",
    }


@pytest.fixture
def sample_query_data():
    """Sample query data for testing."""
    return {
        "request_id": "test-request-123",
        "sql": "SELECT * FROM users WHERE id = ?",
        "parameters": ["1"],
        "duration_ms": 12.34,
        "rows_affected": 1,
        "connection_name": "sqlite",
    }


@pytest.fixture
def sample_exception_data():
    """Sample exception data for testing."""
    return {
        "request_id": "test-request-123",
        "exception_type": "ValueError",
        "exception_value": "Invalid input",
        "traceback": "Traceback (most recent call last)...",
    }
