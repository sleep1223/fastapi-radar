"""Tests for database models."""

from datetime import datetime, timezone

import pytest
from fastapi_radar.models import (
    BackgroundTask,
    CapturedException,
    CapturedQuery,
    CapturedRequest,
    Span,
    SpanRelation,
    Trace,
)

from tortoise.exceptions import IntegrityError


@pytest.mark.unit
@pytest.mark.asyncio
class TestCapturedRequest:
    """Test CapturedRequest model."""

    async def test_create_captured_request(self, db, sample_request_data):
        """Test creating a captured request."""
        request = await CapturedRequest.create(**sample_request_data)

        assert request.id is not None
        assert request.request_id == "test-request-123"
        assert request.method == "GET"
        assert request.path == "/api/users"
        assert request.status_code == 200
        assert request.created_at is not None

    async def test_request_id_unique(self, db, sample_request_data):
        """Test that request_id must be unique."""
        await CapturedRequest.create(**sample_request_data)

        with pytest.raises(IntegrityError):
            await CapturedRequest.create(**sample_request_data)

    async def test_request_with_queries(self, db, sample_request_data, sample_query_data):
        """Test request with associated queries."""
        request = await CapturedRequest.create(**sample_request_data)

        # Create query linked to request
        # Tortoise FK can be set by object instance
        query_data = sample_query_data.copy()
        query_data["request"] = request
        await CapturedQuery.create(**query_data)

        # Verify relation
        queries = await request.queries.all()
        assert len(queries) == 1
        assert queries[0].sql == sample_query_data["sql"]

    async def test_request_with_exceptions(self, db, sample_request_data, sample_exception_data):
        """Test request with associated exceptions."""
        request = await CapturedRequest.create(**sample_request_data)

        exc_data = sample_exception_data.copy()
        exc_data["request"] = request
        await CapturedException.create(**exc_data)

        exceptions = await request.exceptions.all()
        assert len(exceptions) == 1
        assert exceptions[0].exception_type == "ValueError"

    async def test_cascade_delete(self, db, sample_request_data, sample_query_data):
        """Test that deleting request cascades to queries and exceptions."""
        request = await CapturedRequest.create(**sample_request_data)

        query_data = sample_query_data.copy()
        query_data["request"] = request
        await CapturedQuery.create(**query_data)

        await request.delete()

        count = await CapturedQuery.all().count()
        assert count == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestCapturedQuery:
    """Test CapturedQuery model."""

    async def test_create_captured_query(self, db, sample_query_data, sample_request_data):
        """Test creating a captured query."""
        # Must create request first
        request = await CapturedRequest.create(**sample_request_data)

        query_data = sample_query_data.copy()
        query_data["request"] = request
        query = await CapturedQuery.create(**query_data)

        assert query.id is not None
        assert query.request_id == "test-request-123"
        assert query.sql == sample_query_data["sql"]
        assert query.duration_ms == 12.34

    async def test_query_with_parameters(self, db, sample_request_data):
        """Test query with different parameter types."""
        # Create request first
        request = await CapturedRequest.create(**sample_request_data)

        # List parameters
        query1 = await CapturedQuery.create(
            request=request,
            sql="SELECT * FROM users WHERE id = ?",
            parameters=["1", "2"],
            duration_ms=10.0,
        )

        # Dict parameters
        query2 = await CapturedQuery.create(
            request=request,
            sql="SELECT * FROM users WHERE id = :id",
            parameters={"id": "1"},
            duration_ms=10.0,
        )

        assert isinstance(query1.parameters, list)
        assert isinstance(query2.parameters, dict)


@pytest.mark.unit
@pytest.mark.asyncio
class TestCapturedException:
    """Test CapturedException model."""

    async def test_create_captured_exception(self, db, sample_exception_data, sample_request_data):
        """Test creating a captured exception."""
        request = await CapturedRequest.create(**sample_request_data)

        exc_data = sample_exception_data.copy()
        exc_data["request"] = request
        exception = await CapturedException.create(**exc_data)

        assert exception.id is not None
        assert exception.request_id == "test-request-123"
        assert exception.exception_type == "ValueError"
        assert exception.traceback is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestTrace:
    """Test Trace model."""

    async def test_create_trace(self, db):
        """Test creating a trace."""
        trace = await Trace.create(
            trace_id="abc123",
            service_name="test-service",
            operation_name="GET /users",
            start_time=datetime.now(timezone.utc),
            span_count=3,
            status="ok",
        )

        assert trace.trace_id == "abc123"
        assert trace.service_name == "test-service"
        assert trace.span_count == 3

    async def test_trace_with_spans(self, db):
        """Test trace with associated spans."""
        trace = await Trace.create(
            trace_id="trace-123",
            service_name="test-service",
            operation_name="GET /users",
            start_time=datetime.now(timezone.utc),
        )

        await Span.create(
            span_id="span-123",
            trace=trace,
            operation_name="db.query",
            service_name="test-service",
            start_time=datetime.now(timezone.utc),
        )

        spans = await trace.spans.all()
        assert len(spans) == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestSpan:
    """Test Span model."""

    async def test_create_span(self, db):
        """Test creating a span."""
        # Span needs a trace FK
        trace = await Trace.create(trace_id="trace-123", start_time=datetime.now(timezone.utc))

        span = await Span.create(
            span_id="span-123",
            trace=trace,
            operation_name="db.query",
            service_name="test-service",
            start_time=datetime.now(timezone.utc),
            span_kind="client",
        )

        assert span.span_id == "span-123"
        assert span.trace_id == "trace-123"
        assert span.span_kind == "client"

    async def test_span_with_tags_and_logs(self, db):
        """Test span with tags and logs."""
        trace = await Trace.create(trace_id="trace-123", start_time=datetime.now(timezone.utc))

        span = await Span.create(
            span_id="span-456",
            trace=trace,
            operation_name="db.query",
            service_name="test-service",
            start_time=datetime.now(timezone.utc),
            tags={"db.statement": "SELECT * FROM users", "db.system": "postgresql"},
            logs=[{"timestamp": "2024-01-01T00:00:00", "message": "Query started"}],
        )

        assert "db.statement" in span.tags
        assert len(span.logs) == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestSpanRelation:
    """Test SpanRelation model."""

    async def test_create_span_relation(self, db):
        """Test creating a span relation."""
        relation = await SpanRelation.create(
            trace_id="trace-123",
            parent_span_id="span-parent",
            child_span_id="span-child",
            depth=1,
        )

        assert relation.trace_id == "trace-123"
        assert relation.depth == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestBackgroundTask:
    """Test BackgroundTask model."""

    async def test_create_background_task(self, db):
        """Test creating a background task."""
        task = await BackgroundTask.create(
            task_id="task-123",
            request_id="request-123",
            name="send_email",
            status="pending",
            start_time=datetime.now(timezone.utc),
        )

        assert task.task_id == "task-123"
        assert task.name == "send_email"
        assert task.status == "pending"

    async def test_background_task_completion(self, db):
        """Test completing a background task."""
        from datetime import timedelta

        start_time = datetime.now(timezone.utc)
        task = await BackgroundTask.create(
            task_id="task-456",
            name="process_data",
            status="running",
            start_time=start_time,
        )

        # Complete the task
        task.status = "completed"
        task.end_time = start_time + timedelta(milliseconds=150)
        task.duration_ms = 150.5
        await task.save()

        assert task.status == "completed"
        assert task.duration_ms == 150.5
        assert task.end_time > task.start_time

    async def test_background_task_failure(self, db):
        """Test failed background task."""
        task = await BackgroundTask.create(
            task_id="task-789",
            name="failing_task",
            status="failed",
            start_time=datetime.now(timezone.utc),
            error="Task failed due to network error",
        )

        assert task.status == "failed"
        assert task.error is not None
