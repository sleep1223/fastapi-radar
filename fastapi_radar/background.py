"""Background task monitoring for FastAPI Radar."""

import inspect
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from .models import BackgroundTask


def track_background_task():
    """Decorator to track background tasks.

    Usage:
    @track_background_task()
    async def my_task(): ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            task_id = str(uuid.uuid4())
            # Extract request_id from kwargs if provided
            req_id = kwargs.pop("_radar_request_id", None)
            # Clean task name (just function name, not full module path)
            task_name = func.__name__

            # Create task record
            try:
                task = await BackgroundTask.create(
                    task_id=task_id,
                    request_id=req_id,
                    name=task_name,
                    status="running",
                    start_time=datetime.now(timezone.utc),
                )
            except Exception:
                # If DB fails, proceed without tracking
                task = None

            start_time = time.time()
            error = None
            status = "failed"

            try:
                result = await func(*args, **kwargs)
                status = "completed"
                return result
            except Exception as e:
                status = "failed"
                error = str(e)
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000

                if task:
                    try:
                        task.status = status
                        task.end_time = datetime.now(timezone.utc)
                        task.duration_ms = duration_ms
                        task.error = error
                        await task.save()
                    except Exception:
                        pass

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # For sync functions, we can't easily use Tortoise ORM (async)
            # We skip tracking for now, or we could try to run async in a thread
            # But that's risky with Tortoise connection loop binding.
            # Best practice: convert background tasks to async if using Radar with Tortoise.
            return func(*args, **kwargs)

        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
