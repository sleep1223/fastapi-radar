"""Tests for RadarMiddleware."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_radar import Radar
from fastapi_radar.middleware import RadarMiddleware
from fastapi_radar.models import CapturedException, CapturedRequest


@pytest.mark.unit
class TestRadarMiddleware:
    """Test RadarMiddleware class."""

    def test_middleware_init(self):
        """Test middleware initialization."""
        middleware = RadarMiddleware(
            app=Mock(),
            exclude_paths=["/health", "/metrics"],
            max_body_size=5000,
            capture_response_body=True,
            enable_tracing=False,
        )

        assert "/health" in middleware.exclude_paths
        assert middleware.max_body_size == 5000
        assert middleware.capture_response_body is True
        assert middleware.enable_tracing is False

    def test_should_skip_excluded_paths(self):
        """Test that excluded paths are skipped."""
        middleware = RadarMiddleware(
            app=Mock(),
            exclude_paths=["/health", "/__radar"],
        )

        # Create mock requests
        health_request = Mock()
        health_request.url.path = "/health"

        radar_request = Mock()
        radar_request.url.path = "/__radar/dashboard"

        normal_request = Mock()
        normal_request.url.path = "/api/users"

        assert middleware._should_skip(health_request) is True
        assert middleware._should_skip(radar_request) is True
        assert middleware._should_skip(normal_request) is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestMiddlewareIntegration:
    """Integration tests for middleware with FastAPI."""

    async def test_middleware_captures_request(self, db):
        """Test that middleware captures HTTP requests."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        # Add a test endpoint
        @app.get("/test")
        async def test_endpoint():
            return {"message": "Hello"}

        # Use TestClient (sync)
        with TestClient(app) as client:
            response = client.get("/test")
            assert response.status_code == 200

        # Verify request was captured
        requests = await CapturedRequest.all()
        assert len(requests) > 0

        captured = requests[-1]
        assert captured.method == "GET"
        assert "/test" in captured.path
        assert captured.status_code == 200
        assert captured.duration_ms is not None

    async def test_middleware_captures_request_body(self, db):
        """Test that middleware captures request body."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.post("/api/data")
        async def post_data(data: dict):
            return data

        with TestClient(app) as client:
            response = client.post("/api/data", json={"name": "John", "age": 30})
            assert response.status_code == 200

        # Verify request body was captured
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/api/data" in r.path][-1]

        assert captured.body is not None
        assert "John" in captured.body

    async def test_middleware_captures_query_params(self, db):
        """Test that middleware captures query parameters."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/search")
        async def search(q: str, page: int = 1):
            return {"query": q, "page": page}

        with TestClient(app) as client:
            response = client.get("/search?q=test&page=2")
            assert response.status_code == 200

        # Verify query params were captured
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/search" in r.path][-1]

        assert captured.query_params is not None
        assert captured.query_params["q"] == "test"
        assert captured.query_params["page"] == "2"

    async def test_middleware_captures_headers(self, db):
        """Test that middleware captures request headers."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/api/protected")
        async def protected():
            return {"status": "ok"}

        with TestClient(app) as client:
            response = client.get(
                "/api/protected",
                headers={
                    "User-Agent": "TestClient/1.0",
                    "X-Custom-Header": "CustomValue",
                },
            )
            assert response.status_code == 200

        # Verify headers were captured
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/api/protected" in r.path][-1]

        assert captured.headers is not None
        # Check case-insensitivity or lowercase normalization
        headers = {k.lower(): v for k, v in captured.headers.items()}
        assert "user-agent" in headers
        assert "x-custom-header" in headers

    async def test_middleware_captures_exception(self, db):
        """Test that middleware captures exceptions."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        with TestClient(app) as client:
            with pytest.raises(Exception):
                client.get("/error")

        # Verify exception was captured
        exceptions = await CapturedException.all()
        assert len(exceptions) > 0

        captured = exceptions[-1]
        assert captured.exception_type == "ValueError"
        assert "Test error" in captured.exception_value

    async def test_middleware_excludes_paths(self, db):
        """Test that excluded paths are not captured."""
        app = FastAPI()
        radar = Radar(
            app,
            exclude_paths=["/health"],
        )
        await radar.create_tables()

        @app.get("/health")
        async def health():
            return {"status": "healthy"}

        with TestClient(app) as client:
            initial_count = await CapturedRequest.all().count()

            # Make request to excluded path
            response = client.get("/health")
            assert response.status_code == 200

            # Verify request was NOT captured
            final_count = await CapturedRequest.all().count()
            assert final_count == initial_count

    async def test_middleware_handles_large_bodies(self, db):
        """Test that large bodies are truncated."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.post("/upload")
        async def upload(data: dict):
            return {"status": "ok"}

        # Create large payload
        large_data = {"data": "A" * 50000}

        with TestClient(app) as client:
            response = client.post("/upload", json=large_data)
            assert response.status_code == 200

        # Verify body was truncated
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/upload" in r.path][-1]

        assert captured.body is not None
        assert len(captured.body) < 50000
        assert "[truncated" in captured.body

    async def test_middleware_redacts_sensitive_data(self, db):
        """Test that sensitive data is redacted."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.post("/login")
        async def login(credentials: dict):
            return {"status": "ok"}

        with TestClient(app) as client:
            response = client.post(
                "/login",
                json={"username": "john", "password": "secret123"},
                headers={"Authorization": "Bearer token123"},
            )
            assert response.status_code == 200

        # Verify sensitive data was redacted
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/login" in r.path][-1]

        # Check body redaction
        assert "secret123" not in captured.body
        assert "***REDACTED***" in captured.body

        # Check header redaction
        headers = {k.lower(): v for k, v in captured.headers.items()}
        assert headers["authorization"] == "***REDACTED***"

    async def test_middleware_measures_duration(self, db):
        """Test that request duration is measured."""
        import asyncio

        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/slow")
        async def slow_endpoint():
            await asyncio.sleep(0.1)  # 100ms
            return {"status": "ok"}

        with TestClient(app) as client:
            response = client.get("/slow")
            assert response.status_code == 200

        # Verify duration was captured
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/slow" in r.path][-1]

        assert captured.duration_ms is not None
        assert captured.duration_ms >= 100

    async def test_middleware_captures_client_ip(self, db):
        """Test that client IP is captured."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/ip-test")
        async def ip_test():
            return {"status": "ok"}

        with TestClient(app) as client:
            response = client.get("/ip-test", headers={"X-Forwarded-For": "203.0.113.1"})
            assert response.status_code == 200

        # Verify IP was captured
        requests = await CapturedRequest.all()
        captured = [r for r in requests if "/ip-test" in r.path][-1]

        assert captured.client_ip == "203.0.113.1"

    async def test_request_context_isolation(self, db):
        """Test that request contexts are isolated."""
        app = FastAPI()
        radar = Radar(app)
        await radar.create_tables()

        @app.get("/context-test")
        async def context_test():
            # Request context should be set during middleware processing
            return {"status": "ok"}

        with TestClient(app) as client:
            # Make multiple requests
            response1 = client.get("/context-test")
            response2 = client.get("/context-test")

            assert response1.status_code == 200
            assert response2.status_code == 200

        # Verify both requests were captured with different IDs
        requests = await CapturedRequest.all()
        captured_requests = [r for r in requests if "/context-test" in r.path]

        assert len(captured_requests) >= 2
        request_ids = [r.request_id for r in captured_requests]
        assert len(set(request_ids)) == len(captured_requests)  # All unique
