"""Tortoise ORM query capture for FastAPI Radar."""

import time
from typing import Any, Dict, List, Union

from .middleware import request_context
from .models import CapturedQuery
from .tortoise_patch import QueryListener, add_query_listener, apply_tortoise_patch
from .tracing import get_current_trace_context
from .utils import format_sql


class QueryCapture(QueryListener):
    def __init__(
        self,
        capture_bindings: bool = True,
        slow_query_threshold: int = 100,
    ):
        self.capture_bindings = capture_bindings
        self.slow_query_threshold = slow_query_threshold

        # Apply patch and register listener
        apply_tortoise_patch()
        add_query_listener(self)

    async def before_query(self, query: str, values: list | None) -> Any:
        # Prevent infinite loops by ignoring queries to radar tables
        upper_query = query.strip().upper()
        if "radar_" in query:
            # Ignore internal radar queries
            return None

        # Check if it is a DDL statement
        is_ddl = any(upper_query.startswith(cmd) for cmd in ["CREATE", "DROP", "ALTER"])
        if is_ddl:
            return None

        request_id = request_context.get()

        start_time = time.time()
        context = {"start_time": start_time, "request_id": request_id}

        trace_ctx = get_current_trace_context()
        if trace_ctx:
            formatted_sql = format_sql(query)
            operation_type = self._get_operation_type(query)
            db_tags = {
                "db.system": "tortoise",
                "db.statement": formatted_sql[:500],
                "db.operation_type": operation_type,
            }
            span_id = trace_ctx.create_span(
                operation_name=f"DB {operation_type}",
                span_kind="client",
                tags=db_tags,
            )
            context["span_id"] = span_id

        return context

    async def after_query(self, ctx: Any, query: str, values: list | None, result: Any, exc: Exception | None) -> None:
        if not ctx:
            return

        request_id = ctx.get("request_id")
        start_time = ctx.get("start_time")
        span_id = ctx.get("span_id")

        if not start_time:
            return

        duration_ms = round((time.time() - start_time) * 1000, 2)

        rows_affected = None
        # Tortoise execute_query usually returns (rows_affected, resultset)
        if isinstance(result, tuple) and len(result) >= 1:
            rows_affected = result[0]

        trace_ctx = get_current_trace_context()
        if trace_ctx and span_id:
            additional_tags = {
                "db.duration_ms": duration_ms,
                "db.rows_affected": rows_affected,
            }
            if exc:
                additional_tags["error"] = True
                additional_tags["error.message"] = str(exc)

            status = "ok"
            if exc:
                status = "error"
            elif duration_ms >= self.slow_query_threshold:
                status = "slow"
                additional_tags["db.slow_query"] = True

            trace_ctx.finish_span(span_id, status=status, tags=additional_tags)

        # Save captured query
        try:
            params_serialized = None
            if self.capture_bindings and values:
                params_serialized = self._serialize_parameters(values)

            await CapturedQuery.create(
                request_id=request_id,
                sql=format_sql(query),
                parameters=params_serialized,
                duration_ms=duration_ms,
                rows_affected=rows_affected,
                connection_name="default",
            )
        except Exception:
            # Prevent monitoring from breaking app
            pass

    def _get_operation_type(self, statement: str) -> str:
        if not statement:
            return "unknown"

        statement = statement.strip().upper()

        if statement.startswith("SELECT"):
            return "SELECT"
        elif statement.startswith("INSERT"):
            return "INSERT"
        elif statement.startswith("UPDATE"):
            return "UPDATE"
        elif statement.startswith("DELETE"):
            return "DELETE"
        elif statement.startswith("CREATE"):
            return "CREATE"
        elif statement.startswith("DROP"):
            return "DROP"
        elif statement.startswith("ALTER"):
            return "ALTER"
        else:
            return "OTHER"

    def _serialize_parameters(self, parameters: Any) -> Union[Dict[str, str], List[str], None]:
        """Serialize query parameters for storage."""
        if not parameters:
            return None

        try:
            if isinstance(parameters, (list, tuple)):
                return [str(p) for p in parameters[:100]]
            elif isinstance(parameters, dict):
                return {k: str(v) for k, v in list(parameters.items())[:100]}
            return [str(parameters)]
        except Exception:
            return None
