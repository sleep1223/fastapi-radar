"""Comprehensive integration tests."""

import time

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from fastapi_radar import Radar, track_background_task
from fastapi_radar.models import (
    BackgroundTask,
    CapturedException,
    CapturedQuery,
    CapturedRequest,
)

from tortoise import Tortoise, fields, models


# Test Model
class User(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=50)
    email = fields.CharField(max_length=100)

    class Meta:
        table = "users"


@pytest.mark.integration
@pytest.mark.asyncio
class TestEndToEndScenarios:
    """End-to-end integration tests."""

    async def test_complete_crud_flow_with_monitoring(self):
        """Test complete CRUD flow with all monitoring features."""
        # Setup application with database
        app = FastAPI()

        # Setup Radar
        radar = Radar(app)

        # Initialize Tortoise
        # We need to register both our test models and Radar models
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["tests.test_integration", "fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        # Create endpoints
        @app.post("/users")
        async def create_user(name: str, email: str):
            user = await User.create(name=name, email=email)
            return {"id": user.id, "name": user.name, "email": user.email}

        @app.get("/users/{user_id}")
        async def get_user(user_id: int):
            user = await User.filter(id=user_id).first()
            if not user:
                return {"error": "User not found"}, 404
            return {"id": user.id, "name": user.name, "email": user.email}

        @app.put("/users/{user_id}")
        async def update_user(user_id: int, name: str = None, email: str = None):
            user = await User.filter(id=user_id).first()
            if not user:
                return {"error": "User not found"}, 404
            if name:
                user.name = name
            if email:
                user.email = email
            await user.save()
            return {"id": user.id, "name": user.name, "email": user.email}

        @app.delete("/users/{user_id}")
        async def delete_user(user_id: int):
            count = await User.filter(id=user_id).delete()
            if not count:
                return {"error": "User not found"}, 404
            return {"message": "User deleted"}

        # Use TestClient for HTTP requests
        with TestClient(app) as client:
            # 1. CREATE
            response = client.post("/users?name=Alice&email=alice@example.com")
            assert response.status_code == 200
            user_id = response.json()["id"]

            # 2. READ
            response = client.get(f"/users/{user_id}")
            assert response.status_code == 200
            assert response.json()["name"] == "Alice"

            # 3. UPDATE
            response = client.put(f"/users/{user_id}?name=Alice Updated")
            assert response.status_code == 200
            assert response.json()["name"] == "Alice Updated"

            # 4. DELETE
            response = client.delete(f"/users/{user_id}")
            assert response.status_code == 200

        # Verify monitoring data
        # Should have 4 requests
        request_count = await CapturedRequest.all().count()
        assert request_count >= 4

        # Should have captured queries
        query_count = await CapturedQuery.all().count()
        assert query_count > 0

        # Verify query types
        queries = await CapturedQuery.all()
        query_sqls = [q.sql for q in queries]
        # Note: Tortoise/SQLite might generate different SQL, but basic keywords should be there
        assert any("INSERT" in sql.upper() for sql in query_sqls)
        assert any("SELECT" in sql.upper() for sql in query_sqls)
        assert any("UPDATE" in sql.upper() for sql in query_sqls)
        assert any("DELETE" in sql.upper() for sql in query_sqls)

        await Tortoise.close_connections()

    async def test_error_handling_and_exception_tracking(self):
        """Test error handling with exception tracking."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.get("/error/value")
        async def value_error():
            raise ValueError("Test value error")

        @app.get("/error/type")
        async def type_error():
            raise TypeError("Test type error")

        @app.get("/error/key")
        async def key_error():
            data = {}
            return data["missing_key"]

        with TestClient(app) as client:
            # Trigger errors
            with pytest.raises(Exception):  # TestClient re-raises app exceptions
                client.get("/error/value")

            with pytest.raises(Exception):
                client.get("/error/type")

            with pytest.raises(Exception):
                client.get("/error/key")

        # Verify exceptions were captured
        exception_count = await CapturedException.all().count()
        assert exception_count >= 3

        exceptions = await CapturedException.all()
        exception_types = [e.exception_type for e in exceptions]
        assert "ValueError" in exception_types
        assert "TypeError" in exception_types
        assert "KeyError" in exception_types

        await Tortoise.close_connections()

    async def test_background_tasks_integration(self):
        """Test background tasks with monitoring."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        # Create tracked background task
        @track_background_task()
        async def send_email(to: str, subject: str):
            import asyncio

            await asyncio.sleep(0.05)
            return f"Email sent to {to}"

        @app.post("/send-notification")
        async def send_notification(background_tasks: BackgroundTasks, email: str):
            background_tasks.add_task(send_email, email, "Test Subject")
            return {"status": "notification queued"}

        with TestClient(app) as client:
            # Send notification
            response = client.post("/send-notification?email=test@example.com")
            assert response.status_code == 200

        # Verify task was tracked
        tasks = await BackgroundTask.all()
        assert len(tasks) >= 1

        task = tasks[-1]
        assert task.name == "send_email"
        # Status might be pending or completed depending on timing
        assert task.status in ["completed", "running", "pending"]

        await Tortoise.close_connections()

    async def test_concurrent_requests(self):
        """Test handling concurrent requests."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.get("/endpoint/{id}")
        async def get_data(id: int):
            import asyncio

            await asyncio.sleep(0.01)
            return {"id": id, "data": f"data-{id}"}

        with TestClient(app) as client:
            # Make multiple requests
            responses = []
            for i in range(10):
                response = client.get(f"/endpoint/{i}")
                responses.append(response)

            # All should succeed
            assert all(r.status_code == 200 for r in responses)

        # All should be tracked
        request_count = await CapturedRequest.filter(path__contains="/endpoint/").count()
        assert request_count >= 10

        requests = await CapturedRequest.filter(path__contains="/endpoint/")
        request_ids = [r.request_id for r in requests]
        assert len(set(request_ids)) == len(requests)

        await Tortoise.close_connections()

    async def test_large_payloads(self):
        """Test handling large request/response payloads."""
        app = FastAPI()
        radar = Radar(app, max_body_size=1000)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.post("/upload")
        async def upload(data: dict):
            return {"status": "received", "size": len(str(data))}

        with TestClient(app) as client:
            # Send large payload
            large_data = {"content": "A" * 10000}
            response = client.post("/upload", json=large_data)
            assert response.status_code == 200

        # Verify body was truncated
        requests = await CapturedRequest.filter(path__contains="/upload")
        captured = requests[-1]

        assert captured.body is not None
        assert len(captured.body) < len(str(large_data))

        await Tortoise.close_connections()

    async def test_performance_with_many_requests(self):
        """Test performance with many requests."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.get("/fast")
        async def fast_endpoint():
            return {"status": "ok"}

        with TestClient(app) as client:
            # Make many requests
            start_time = time.time()
            num_requests = 50

            for _ in range(num_requests):
                response = client.get("/fast")
                assert response.status_code == 200

            elapsed = time.time() - start_time
            # Should complete in reasonable time
            assert elapsed < 5.0

        # Verify all were captured
        count = await CapturedRequest.filter(path__contains="/fast").count()
        assert count == num_requests

        await Tortoise.close_connections()


@pytest.mark.integration
@pytest.mark.asyncio
class TestDashboardIntegration:
    """Test dashboard integration."""

    async def test_dashboard_serves_stats(self):
        """Test that dashboard can retrieve and display stats."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.get("/api/data")
        async def get_data():
            return {"data": [1, 2, 3]}

        with TestClient(app) as client:
            # Generate some activity
            for _ in range(5):
                client.get("/api/data")

            # Dashboard stats should be available
            response = client.get("/__radar/api/stats?hours=1")
            assert response.status_code == 200

            stats = response.json()
            assert stats["total_requests"] >= 5

        await Tortoise.close_connections()

    async def test_dashboard_displays_request_details(self):
        """Test that dashboard can display request details."""
        app = FastAPI()
        radar = Radar(app)

        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["fastapi_radar.models"]})
        await Tortoise.generate_schemas()

        @app.post("/api/users")
        async def create_user(data: dict):
            return {"id": 1, "name": data.get("name")}

        with TestClient(app) as client:
            # Create a request
            response = client.post("/api/users", json={"name": "John", "age": 30})
            assert response.status_code == 200

            # Get request list
            response = client.get("/__radar/api/requests")
            assert response.status_code == 200

            requests = response.json()
            assert len(requests) > 0

            # Get request detail
            request_id = requests[0]["request_id"]
            response = client.get(f"/__radar/api/requests/{request_id}")
            assert response.status_code == 200

            detail = response.json()
            assert detail["request_id"] == request_id
            assert detail["method"] in ["POST", "GET"]

        await Tortoise.close_connections()
