"""Test suite for FastAPI Radar core functionality."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_radar import Radar
from fastapi_radar.models import CapturedRequest

from tortoise import Tortoise


@pytest.mark.unit
class TestRadarInitialization:
    """Test Radar initialization."""

    def test_radar_basic_initialization(self):
        """Test basic Radar initialization."""
        app = FastAPI()
        radar = Radar(app)

        assert radar is not None
        assert radar.app == app
        # db_engine is no longer a property of Radar

    def test_radar_custom_config(self):
        """Test Radar with custom configuration."""
        app = FastAPI()
        radar = Radar(
            app,
            dashboard_path="/custom-radar",
            max_requests=500,
            retention_hours=12,
            slow_query_threshold=200,
            capture_sql_bindings=False,
            exclude_paths=["/health", "/metrics"],
            theme="dark",
        )

        assert radar.dashboard_path == "/custom-radar"
        assert radar.max_requests == 500
        assert radar.retention_hours == 12
        assert radar.slow_query_threshold == 200
        assert radar.capture_sql_bindings is False
        assert "/health" in radar.exclude_paths
        assert radar.theme == "dark"

    def test_radar_auto_excludes_dashboard_path(self):
        """Test that dashboard path is automatically excluded."""
        app = FastAPI()
        radar = Radar(app)

        assert radar.dashboard_path in radar.exclude_paths


@pytest.mark.unit
@pytest.mark.asyncio
class TestRadarTableManagement:
    """Test Radar table management."""

    async def test_create_tables(self):
        """Test creating tables."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})

        # Should not raise
        await radar.create_tables()

        await Tortoise.close_connections()

    async def test_create_tables_idempotent(self):
        """Test that create_tables can be called multiple times."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})

        await radar.create_tables()
        await radar.create_tables()  # Should not fail

        await Tortoise.close_connections()

    async def test_drop_tables(self):
        """Test dropping tables."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})

        await radar.create_tables()
        await radar.drop_tables()

        # Tables should be dropped
        # Recreating should work
        await radar.create_tables()

        await Tortoise.close_connections()


@pytest.mark.unit
@pytest.mark.asyncio
class TestRadarCleanup:
    """Test Radar cleanup functionality."""

    async def test_cleanup_old_requests(self):
        """Test cleaning up old requests."""
        from datetime import datetime, timedelta, timezone

        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await radar.create_tables()

        # Create old and recent requests
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)

        # We need to manually insert with old created_at
        # Tortoise auto_now_add=True might override it unless we are careful
        # But usually passing it explicitly works if the field allows it.
        # However, created_at is auto_now_add=True.
        # We might need to update it after creation or use a different way.

        req_old = await CapturedRequest.create(
            request_id="old",
            method="GET",
            url="http://test.com",
            path="/old",
        )
        # Hack to update created_at since it's auto_now_add
        req_old.created_at = old_time
        await req_old.save()

        req_recent = await CapturedRequest.create(
            request_id="recent",
            method="GET",
            url="http://test.com",
            path="/recent",
        )

        # Cleanup data older than 24 hours
        deleted_count = await radar.cleanup(older_than_hours=24)

        assert deleted_count >= 1

        # Verify old request was deleted
        remaining = await CapturedRequest.all()
        assert len(remaining) == 1
        assert remaining[0].request_id == "recent"

        await Tortoise.close_connections()


@pytest.mark.integration
@pytest.mark.asyncio
class TestRadarFullIntegration:
    """Full integration tests for Radar."""

    async def test_full_request_lifecycle(self):
        """Test full request lifecycle capture."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await radar.create_tables()

        @app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        # Use TestClient (sync)
        with TestClient(app) as client:
            response = client.get("/test?param=value")

            assert response.status_code == 200
            assert response.json() == {"message": "test"}

        # Verify request was captured
        requests = await CapturedRequest.all()
        assert len(requests) > 0

        captured = requests[-1]
        assert captured.method == "GET"
        assert "/test" in captured.path
        assert captured.status_code == 200
        # Check query params (might be stored as dict or string depending on impl)
        # Radar stores it as JSONField, so it should be a dict
        assert captured.query_params.get("param") == "value"

        await Tortoise.close_connections()

    async def test_dashboard_accessible(self):
        """Test that dashboard is accessible."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await radar.create_tables()

        with TestClient(app) as client:
            response = client.get("/__radar")
            # Might be 200 or 307 redirect
            assert response.status_code in [200, 307]

        await Tortoise.close_connections()

    async def test_api_endpoints_accessible(self):
        """Test that API endpoints are accessible."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await radar.create_tables()

        with TestClient(app) as client:
            # Test various API endpoints
            response = client.get("/__radar/api/stats?hours=1")
            assert response.status_code == 200

            response = client.get("/__radar/api/requests")
            assert response.status_code == 200

            response = client.get("/__radar/api/queries")
            assert response.status_code == 200

            response = client.get("/__radar/api/exceptions")
            assert response.status_code == 200

        await Tortoise.close_connections()
