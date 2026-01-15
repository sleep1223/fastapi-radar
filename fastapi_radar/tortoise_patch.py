import asyncio
from typing import Any, List, Protocol


class QueryListener(Protocol):
    async def before_query(self, query: str, values: list | None) -> Any: ...
    async def after_query(self, ctx: Any, query: str, values: list | None, result: Any, exc: Exception | None) -> None: ...


_listeners: List[QueryListener] = []


def add_query_listener(listener: QueryListener):
    """Register a global query listener."""
    _listeners.append(listener)


def apply_tortoise_patch():
    """
    Monkey patch Tortoise ORM backends to support query interception.
    """
    targets = []

    # Try to import common backends
    try:
        from tortoise.backends.sqlite.client import SqliteClient

        targets.append(SqliteClient)
    except ImportError:
        pass

    try:
        from tortoise.backends.asyncpg.client import AsyncpgDBClient

        targets.append(AsyncpgDBClient)
    except ImportError:
        pass

    try:
        from tortoise.backends.mysql.client import MySQLClient

        targets.append(MySQLClient)
    except ImportError:
        pass

    for client_cls in targets:
        # Avoid double patching
        if getattr(client_cls, "_radar_patched", False):
            continue

        original_execute_query = client_cls.execute_query
        original_execute_script = getattr(client_cls, "execute_script", None)
        original_execute_insert = getattr(client_cls, "execute_insert", None)

        async def new_execute_query(self, query: str, values: list | None = None, *args, **kwargs):
            # Skip internal queries if needed, or rely on listeners to filter

            ctxs = []
            for listener in _listeners:
                try:
                    if asyncio.iscoroutinefunction(listener.before_query):
                        ctx = await listener.before_query(query, values)
                    else:
                        ctx = listener.before_query(query, values)
                    ctxs.append(ctx)
                except Exception:
                    # Log error?
                    ctxs.append(None)

            exc = None
            result = None

            try:
                result = await original_execute_query(self, query, values, *args, **kwargs)
                return result
            except Exception as e:
                exc = e
                raise e
            finally:
                for i, listener in enumerate(_listeners):
                    try:
                        if asyncio.iscoroutinefunction(listener.after_query):
                            await listener.after_query(ctxs[i], query, values, result, exc)
                        else:
                            listener.after_query(ctxs[i], query, values, result, exc)
                    except Exception:
                        pass

        async def new_execute_script(self, query: str, *args, **kwargs):
            ctxs = []
            values = []  # Script usually has no values binding
            for listener in _listeners:
                try:
                    if asyncio.iscoroutinefunction(listener.before_query):
                        ctx = await listener.before_query(query, values)
                    else:
                        ctx = listener.before_query(query, values)
                    ctxs.append(ctx)
                except Exception:
                    ctxs.append(None)

            exc = None
            result = None

            try:
                if original_execute_script:
                    result = await original_execute_script(self, query, *args, **kwargs)
                return result
            except Exception as e:
                exc = e
                raise e
            finally:
                for i, listener in enumerate(_listeners):
                    try:
                        if asyncio.iscoroutinefunction(listener.after_query):
                            await listener.after_query(ctxs[i], query, values, result, exc)
                        else:
                            listener.after_query(ctxs[i], query, values, result, exc)
                    except Exception:
                        pass

        async def new_execute_insert(self, query: str, values: list, *args, **kwargs):
            ctxs = []
            for listener in _listeners:
                try:
                    if asyncio.iscoroutinefunction(listener.before_query):
                        ctx = await listener.before_query(query, values)
                    else:
                        ctx = listener.before_query(query, values)
                    ctxs.append(ctx)
                except Exception:
                    ctxs.append(None)

            exc = None
            result = None

            try:
                if original_execute_insert:
                    result = await original_execute_insert(self, query, values, *args, **kwargs)
                return result
            except Exception as e:
                exc = e
                raise e
            finally:
                for i, listener in enumerate(_listeners):
                    try:
                        if asyncio.iscoroutinefunction(listener.after_query):
                            await listener.after_query(ctxs[i], query, values, result, exc)
                        else:
                            listener.after_query(ctxs[i], query, values, result, exc)
                    except Exception:
                        pass

        client_cls.execute_query = new_execute_query
        if original_execute_script:
            client_cls.execute_script = new_execute_script
        if original_execute_insert:
            client_cls.execute_insert = new_execute_insert
        client_cls._radar_patched = True
