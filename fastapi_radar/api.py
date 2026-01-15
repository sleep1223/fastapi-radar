"""API endpoints for FastAPI Radar dashboard."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Union

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from tortoise.functions import Avg, Count

from .models import (
    BackgroundTask,
    CapturedException,
    CapturedQuery,
    CapturedRequest,
    Span,
    Trace,
)
from .tracing import TracingManager


def round_float(value: Optional[float], decimals: int = 2) -> Optional[float]:
    """Round a float value to specified decimal places."""
    if value is None:
        return None
    return round(value, decimals)


class RequestSummary(BaseModel):
    id: int
    request_id: str
    method: str
    path: str
    status_code: Optional[int]
    duration_ms: Optional[float]
    query_count: int
    has_exception: bool
    created_at: datetime


class RequestDetail(BaseModel):
    id: int
    request_id: str
    method: str
    url: str
    path: str
    query_params: Optional[Dict[str, Any]]
    headers: Optional[Dict[str, str]]
    body: Optional[str]
    status_code: Optional[int]
    response_body: Optional[str]
    response_headers: Optional[Dict[str, str]]
    duration_ms: Optional[float]
    client_ip: Optional[str]
    created_at: datetime
    queries: List[Dict[str, Any]]
    exceptions: List[Dict[str, Any]]


class QueryDetail(BaseModel):
    id: int
    request_id: Optional[str]
    sql: str
    parameters: Union[Dict[str, str], List[str], None]
    duration_ms: Optional[float]
    rows_affected: Optional[int]
    connection_name: Optional[str]
    created_at: datetime


class ExceptionDetail(BaseModel):
    id: int
    request_id: Optional[str]
    exception_type: str
    exception_value: Optional[str]
    traceback: str
    created_at: datetime


class DashboardStats(BaseModel):
    total_requests: int
    avg_response_time: Optional[float]
    total_queries: int
    avg_query_time: Optional[float]
    total_exceptions: int
    slow_queries: int
    requests_per_minute: float


class TraceSummary(BaseModel):
    trace_id: str
    service_name: Optional[str]
    operation_name: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    span_count: int
    status: str
    created_at: datetime


class BackgroundTaskSummary(BaseModel):
    id: int
    task_id: str
    request_id: Optional[str]
    name: str
    status: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    error: Optional[str]
    created_at: datetime


class WaterfallSpan(BaseModel):
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    service_name: Optional[str]
    start_time: Optional[str]  # ISO 8601 string
    end_time: Optional[str]  # ISO 8601 string
    duration_ms: Optional[float]
    status: str
    tags: Optional[Dict[str, Any]]
    depth: int
    offset_ms: float  # Offset from trace start in ms


class TraceDetail(BaseModel):
    trace_id: str
    service_name: Optional[str]
    operation_name: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    span_count: int
    status: str
    tags: Optional[Dict[str, Any]]
    created_at: datetime
    spans: List[WaterfallSpan]


def create_api_router(auth_dependency: Optional[Callable] = None) -> APIRouter:
    # Build dependencies list for the router
    dependencies = []
    if auth_dependency:
        dependencies.append(Depends(auth_dependency))

    router = APIRouter(prefix="/__radar/api", tags=["radar"], dependencies=dependencies)

    @router.get("/requests", response_model=List[RequestSummary])
    async def get_requests(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status_code: Optional[int] = None,
        method: Optional[str] = None,
        search: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ):
        query = CapturedRequest.all()

        if start_time:
            query = query.filter(created_at__gte=start_time)
        if end_time:
            query = query.filter(created_at__lte=end_time)
        if status_code:
            if status_code in [200, 300, 400, 500]:
                # Filter by status code range
                lower_bound = status_code
                upper_bound = status_code + 100
                query = query.filter(
                    status_code__gte=lower_bound,
                    status_code__lt=upper_bound,
                )
            else:
                # Exact status code match
                query = query.filter(status_code=status_code)
        if method:
            query = query.filter(method=method)
        if search:
            query = query.filter(path__icontains=search)

        requests = await query.order_by("-created_at").offset(offset).limit(limit).prefetch_related("queries", "exceptions")

        return [
            RequestSummary(
                id=req.id,
                request_id=req.request_id,
                method=req.method,
                path=req.path,
                status_code=req.status_code,
                duration_ms=round_float(req.duration_ms),
                query_count=len(req.queries),
                has_exception=len(req.exceptions) > 0,
                created_at=req.created_at,
            )
            for req in requests
        ]

    @router.get("/requests/{request_id}", response_model=RequestDetail)
    async def get_request_detail(request_id: str):
        request = await CapturedRequest.filter(request_id=request_id).first()

        if not request:
            raise HTTPException(status_code=404, detail="Request not found")

        # Manually fetch related items if not prefetched (Tortoise lazy loading needs await)
        # But we can query them separately or use fetch_related
        # Or better, query CapturedQuery and CapturedException filtering by request_id
        # Since we didn't use strict ForeignKeys in models for request_id (they are strings),
        # we have to query manually.
        # Wait, in models.py I used fields.ReverseRelation["CapturedQuery"].
        # If I want to use that, I need to setup ForeignKey properly.
        # But I said I kept it loose?
        # Let's check models.py again.
        # CapturedQuery has request_id field.
        # CapturedRequest has queries: fields.ReverseRelation["CapturedQuery"]
        # But for ReverseRelation to work, CapturedQuery must have a ForeignKey to CapturedRequest.
        # In models.py I didn't add ForeignKey. I just added request_id CharField.
        # So ReverseRelation won't work automatically.
        # So I have to query manually.

        queries = await CapturedQuery.filter(request_id=request_id).all()
        exceptions = await CapturedException.filter(request_id=request_id).all()

        return RequestDetail(
            id=request.id,
            request_id=request.request_id,
            method=request.method,
            url=request.url,
            path=request.path,
            query_params=request.query_params,
            headers=request.headers,
            body=request.body,
            status_code=request.status_code,
            response_body=request.response_body,
            response_headers=request.response_headers,
            duration_ms=round_float(request.duration_ms),
            client_ip=request.client_ip,
            created_at=request.created_at,
            queries=[
                {
                    "id": q.id,
                    "sql": q.sql,
                    "parameters": q.parameters,
                    "duration_ms": round_float(q.duration_ms),
                    "rows_affected": q.rows_affected,
                    "connection_name": q.connection_name,
                    "created_at": q.created_at,
                }
                for q in queries
            ],
            exceptions=[
                {
                    "id": e.id,
                    "exception_type": e.exception_type,
                    "exception_value": e.exception_value,
                    "traceback": e.traceback,
                    "created_at": e.created_at,
                }
                for e in exceptions
            ],
        )

    @router.get("/requests/{request_id}/curl")
    async def get_request_as_curl(request_id: str):
        request = await CapturedRequest.filter(request_id=request_id).first()

        if not request:
            raise HTTPException(status_code=404, detail="Request not found")

        # Build cURL command
        parts = [f"curl -X {request.method}"]

        # Add headers
        if request.headers:
            for key, value in request.headers.items():
                if key.lower() not in ["host", "content-length"]:
                    parts.append(f"-H '{key}: {value}'")

        # Add body
        if request.body:
            parts.append(f"-d '{request.body}'")

        # Add URL (use full URL if available, otherwise construct from path)
        url = request.url if request.url else request.path
        parts.append(f"'{url}'")

        return {"curl": " ".join(parts)}

    @router.post("/requests/{request_id}/replay")
    async def replay_request(
        request_id: str,
        body: Optional[Dict[str, Any]] = None,
    ):
        """Replay a captured request with optional body override."""
        request = await CapturedRequest.filter(request_id=request_id).first()

        if not request:
            raise HTTPException(status_code=404, detail="Request not found")

        # Security: Validate URL to prevent SSRF attacks
        # ...

        # Build replay request
        headers = dict(request.headers) if request.headers else {}
        # Remove hop-by-hop headers
        headers.pop("host", None)
        headers.pop("content-length", None)
        headers.pop("connection", None)
        headers.pop("keep-alive", None)
        headers.pop("transfer-encoding", None)

        request_body = body if body is not None else request.body

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                response = await client.request(
                    method=request.method,
                    url=request.url,
                    headers=headers,
                    content=(request_body if isinstance(request_body, (str, bytes)) else None),
                    json=request_body if isinstance(request_body, dict) else None,
                )

                # Store the replayed request
                replayed_request = CapturedRequest(
                    request_id=str(uuid.uuid4()),
                    method=request.method,
                    url=request.url,
                    path=request.path,
                    query_params=request.query_params,
                    headers=dict(response.request.headers),
                    body=request_body if isinstance(request_body, str) else None,
                    status_code=response.status_code,
                    response_body=response.text[:10000] if response.text else None,
                    response_headers=dict(response.headers),
                    duration_ms=response.elapsed.total_seconds() * 1000,
                    client_ip="replay",
                )
                await replayed_request.save()

                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text,
                    "elapsed_ms": response.elapsed.total_seconds() * 1000,
                    "original_status": request.status_code,
                    "original_duration_ms": request.duration_ms,
                    "new_request_id": replayed_request.request_id,
                }
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Replay failed: {str(e)}")

    @router.get("/queries", response_model=List[QueryDetail])
    async def get_queries(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        slow_only: bool = Query(False),
        slow_threshold: int = Query(100),
        search: Optional[str] = None,
    ):
        query = CapturedQuery.all()

        if slow_only:
            query = query.filter(duration_ms__gte=slow_threshold)
        if search:
            query = query.filter(sql__icontains=search)

        queries = await query.order_by("-created_at").offset(offset).limit(limit)

        return [
            QueryDetail(
                id=q.id,
                request_id=q.request_id,
                sql=q.sql,
                parameters=q.parameters,
                duration_ms=round_float(q.duration_ms),
                rows_affected=q.rows_affected,
                connection_name=q.connection_name,
                created_at=q.created_at,
            )
            for q in queries
        ]

    @router.get("/exceptions", response_model=List[ExceptionDetail])
    async def get_exceptions(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        exception_type: Optional[str] = None,
    ):
        query = CapturedException.all()

        if exception_type:
            query = query.filter(exception_type=exception_type)

        exceptions = await query.order_by("-created_at").offset(offset).limit(limit)

        return [
            ExceptionDetail(
                id=e.id,
                request_id=e.request_id,
                exception_type=e.exception_type,
                exception_value=e.exception_value,
                traceback=e.traceback,
                created_at=e.created_at,
            )
            for e in exceptions
        ]

    @router.get("/stats", response_model=DashboardStats)
    async def get_stats(
        hours: int = Query(1, ge=1, le=720),
        slow_threshold: int = Query(100),
    ):
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Requests stats
        req_stats = (
            await CapturedRequest
            .filter(created_at__gte=since)
            .annotate(
                total_requests=Count("id"),
                avg_response_time=Avg("duration_ms"),
            )
            .values("total_requests", "avg_response_time")
        )

        if req_stats:
            total_requests = req_stats[0]["total_requests"] or 0
            avg_response_time = req_stats[0]["avg_response_time"] or 0.0
        else:
            total_requests = 0
            avg_response_time = 0.0

        # Queries stats
        # Tortoise doesn't support conditional sum easily in one query without raw SQL or advanced expressions.
        # We can run two queries or use raw SQL.
        # Let's try to use raw SQL for efficiency or just simple count for slow queries.

        query_stats = await CapturedQuery.filter(created_at__gte=since).annotate(total_queries=Count("id"), avg_query_time=Avg("duration_ms")).values("total_queries", "avg_query_time")

        slow_queries = await CapturedQuery.filter(created_at__gte=since, duration_ms__gte=slow_threshold).count()

        if query_stats:
            total_queries = query_stats[0]["total_queries"] or 0
            avg_query_time = query_stats[0]["avg_query_time"] or 0.0
        else:
            total_queries = 0
            avg_query_time = 0.0

        total_exceptions = await CapturedException.filter(created_at__gte=since).count()

        requests_per_minute = total_requests / (hours * 60)

        return DashboardStats(
            total_requests=total_requests,
            avg_response_time=round_float(avg_response_time),
            total_queries=total_queries,
            avg_query_time=round_float(avg_query_time),
            total_exceptions=total_exceptions,
            slow_queries=slow_queries,
            requests_per_minute=round_float(requests_per_minute),
        )

    @router.delete("/clear")
    async def clear_data(older_than_hours: Optional[int] = None):
        if older_than_hours:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
            await CapturedRequest.filter(created_at__lt=cutoff).delete()
        else:
            await CapturedRequest.all().delete()
            # Also clear others? Cascading?
            # CapturedQuery and Exception don't have FKs so we should delete them manually if we want clean state.
            await CapturedQuery.all().delete()
            await CapturedException.all().delete()

        return {"message": "Data cleared successfully"}

    # Tracing-related API endpoints

    @router.get("/traces", response_model=List[TraceSummary])
    async def get_traces(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: Optional[str] = Query(None),
        service_name: Optional[str] = Query(None),
        min_duration_ms: Optional[float] = Query(None),
        hours: int = Query(24, ge=1, le=720),
    ):
        """List traces."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = Trace.filter(created_at__gte=since)

        if status:
            query = query.filter(status=status)
        if service_name:
            query = query.filter(service_name=service_name)
        if min_duration_ms:
            query = query.filter(duration_ms__gte=min_duration_ms)

        traces = await query.order_by("-start_time").offset(offset).limit(limit)

        return [
            TraceSummary(
                trace_id=t.trace_id,
                service_name=t.service_name,
                operation_name=t.operation_name,
                start_time=t.start_time,
                end_time=t.end_time,
                duration_ms=round_float(t.duration_ms),
                span_count=t.span_count,
                status=t.status,
                created_at=t.created_at,
            )
            for t in traces
        ]

    @router.get("/traces/{trace_id}", response_model=TraceDetail)
    async def get_trace_detail(trace_id: str):
        """Get trace details."""
        trace = await Trace.filter(trace_id=trace_id).first()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")

        # Fetch waterfall data
        tracing_manager = TracingManager()
        waterfall_spans = await tracing_manager.get_waterfall_data(trace_id)

        return TraceDetail(
            trace_id=trace.trace_id,
            service_name=trace.service_name,
            operation_name=trace.operation_name,
            start_time=trace.start_time,
            end_time=trace.end_time,
            duration_ms=round_float(trace.duration_ms),
            span_count=trace.span_count,
            status=trace.status,
            tags=trace.tags,
            created_at=trace.created_at,
            spans=[WaterfallSpan(**span) for span in waterfall_spans],
        )

    @router.get("/traces/{trace_id}/waterfall")
    async def get_trace_waterfall(trace_id: str):
        """Get optimized waterfall data for a trace."""
        trace = await Trace.filter(trace_id=trace_id).first()
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")

        tracing_manager = TracingManager()
        waterfall_data = await tracing_manager.get_waterfall_data(trace_id)

        return {
            "trace_id": trace_id,
            "spans": waterfall_data,
            "trace_info": {
                "service_name": trace.service_name,
                "operation_name": trace.operation_name,
                "total_duration_ms": trace.duration_ms,
                "span_count": trace.span_count,
                "status": trace.status,
            },
        }

    @router.get("/spans/{span_id}")
    async def get_span_detail(span_id: str):
        """Get span details."""
        span = await Span.filter(span_id=span_id).first()
        if not span:
            raise HTTPException(status_code=404, detail="Span not found")

        return {
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "parent_span_id": span.parent_span_id,
            "operation_name": span.operation_name,
            "service_name": span.service_name,
            "span_kind": span.span_kind,
            "start_time": span.start_time.isoformat() if span.start_time else None,
            "end_time": span.end_time.isoformat() if span.end_time else None,
            "duration_ms": span.duration_ms,
            "status": span.status,
            "tags": span.tags,
            "logs": span.logs,
            "created_at": span.created_at.isoformat(),
        }

    @router.get("/background-tasks", response_model=List[BackgroundTaskSummary])
    async def get_background_tasks(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        status: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """Get background tasks with optional filters."""
        query = BackgroundTask.all()

        if status:
            query = query.filter(status=status)
        if request_id:
            query = query.filter(request_id=request_id)

        tasks = await query.order_by("-created_at").offset(offset).limit(limit)

        return [
            BackgroundTaskSummary(
                id=task.id,
                task_id=task.task_id,
                request_id=task.request_id,
                name=task.name,
                status=task.status,
                start_time=task.start_time,
                end_time=task.end_time,
                duration_ms=round_float(task.duration_ms),
                error=task.error,
                created_at=task.created_at,
            )
            for task in tasks
        ]

    return router
