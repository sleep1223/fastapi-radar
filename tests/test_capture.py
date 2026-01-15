"""Tests for query capture functionality."""

import pytest
from fastapi_radar.capture import QueryCapture
from fastapi_radar.middleware import request_context
from fastapi_radar.models import CapturedQuery

from tortoise import Tortoise


@pytest.mark.unit
@pytest.mark.asyncio
class TestQueryCapture:
    """Test QueryCapture class."""

    async def test_init(self, db):
        """Test QueryCapture initialization."""
        capture = QueryCapture(
            capture_bindings=True,
            slow_query_threshold=100,
        )
        assert capture.capture_bindings is True
        assert capture.slow_query_threshold == 100

    async def test_get_operation_type(self, db):
        """Test determining operation type from SQL."""
        capture = QueryCapture()

        test_cases = [
            ("SELECT * FROM users", "SELECT"),
            ("INSERT INTO users VALUES (1)", "INSERT"),
            ("UPDATE users SET name = 'John'", "UPDATE"),
            ("DELETE FROM users WHERE id = 1", "DELETE"),
            ("CREATE TABLE users (id INT)", "CREATE"),
            ("DROP TABLE users", "DROP"),
            ("ALTER TABLE users ADD COLUMN age INT", "ALTER"),
            ("  select * from users", "SELECT"),  # lowercase
            ("EXPLAIN SELECT * FROM users", "OTHER"),
        ]

        for sql, expected in test_cases:
            result = capture._get_operation_type(sql)
            assert result == expected, f"Failed for SQL: {sql}"

    async def test_serialize_parameters_list(self, db):
        """Test serializing list parameters."""
        capture = QueryCapture()

        params = ["value1", "value2", 123]
        result = capture._serialize_parameters(params)

        assert isinstance(result, list)
        assert result == ["value1", "value2", "123"]

    async def test_serialize_parameters_dict(self, db):
        """Test serializing dict parameters."""
        capture = QueryCapture()

        params = {"id": 1, "name": "John", "active": True}
        result = capture._serialize_parameters(params)

        assert isinstance(result, dict)
        assert result == {"id": "1", "name": "John", "active": "True"}

    async def test_serialize_parameters_none(self, db):
        """Test serializing None parameters."""
        capture = QueryCapture()

        result = capture._serialize_parameters(None)
        assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestQueryCaptureIntegration:
    """Integration tests for query capture."""

    async def test_capture_real_queries(self, db):
        """Test capturing real database queries."""
        # Create a captured request first to satisfy FK constraint
        from fastapi_radar.models import CapturedRequest

        await CapturedRequest.create(request_id="integration-test-123", method="GET", path="/test", url="http://testserver/test")

        # Initialize capture (it patches Tortoise)
        capture = QueryCapture(capture_bindings=True)

        # Set request context
        request_context.set("integration-test-123")

        # Execute a query using Tortoise
        conn = Tortoise.get_connection("default")
        await conn.execute_query("CREATE TABLE IF NOT EXISTS test_users (id INTEGER, name TEXT)")
        await conn.execute_query("INSERT INTO test_users (id, name) VALUES (?, ?)", [1, "Alice"])

        # Verify query was captured
        captured_queries = await CapturedQuery.all()
        assert len(captured_queries) > 0

        # Find the INSERT query
        insert_queries = [q for q in captured_queries if "INSERT" in q.sql.upper()]
        assert len(insert_queries) > 0

        # Verify request ID
        assert insert_queries[0].request_id == "integration-test-123"
