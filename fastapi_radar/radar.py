"""Main Radar class for FastAPI Radar."""

import os
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import FastAPI

from tortoise import Tortoise

from .api import create_api_router
from .capture import QueryCapture
from .middleware import RadarMiddleware
from .models import CapturedRequest


def is_reload_worker() -> bool:
    """Check if we're running in a reload worker process (used by fastapi dev)."""
    if os.environ.get("UVICORN_RELOAD"):
        return True

    if os.environ.get("WERKZEUG_RUN_MAIN"):
        return True

    return False


class Radar:
    query_capture: Optional[QueryCapture]

    def __init__(
        self,
        app: FastAPI,
        dashboard_path: str = "/__radar",
        max_requests: int = 1000,
        retention_hours: int = 24,
        slow_query_threshold: int = 100,
        capture_sql_bindings: bool = True,
        exclude_paths: Optional[List[str]] = None,
        theme: str = "auto",
        enable_tracing: bool = True,
        service_name: str = "fastapi-app",
        include_in_schema: bool = True,
        auth_dependency: Optional[Callable] = None,
        max_body_size: int = 10000,
    ):
        self.app = app
        self.dashboard_path = dashboard_path
        self.max_requests = max_requests
        self.retention_hours = retention_hours
        self.slow_query_threshold = slow_query_threshold
        self.capture_sql_bindings = capture_sql_bindings
        self.exclude_paths = exclude_paths or []
        self.theme = theme
        self.enable_tracing = enable_tracing
        self.service_name = service_name
        self.auth_dependency = auth_dependency
        self.max_body_size = max_body_size
        self.query_capture = None

        if dashboard_path not in self.exclude_paths:
            self.exclude_paths.append(dashboard_path)
        self.exclude_paths.append("/favicon.ico")

        self._setup_middleware()
        self._setup_query_capture()
        self._setup_api(include_in_schema=include_in_schema)
        self._setup_dashboard(include_in_schema=include_in_schema)

        # Register cleanup task on startup?
        # Or just let user call cleanup.
        # Original code didn't auto cleanup.

    def _setup_middleware(self) -> None:
        """Add request capture middleware."""
        self.app.add_middleware(
            RadarMiddleware,
            exclude_paths=self.exclude_paths,
            max_body_size=self.max_body_size,
            capture_response_body=True,
            enable_tracing=self.enable_tracing,
            service_name=self.service_name,
        )

    def _setup_query_capture(self) -> None:
        """Setup Tortoise ORM query capture."""
        self.query_capture = QueryCapture(
            capture_bindings=self.capture_sql_bindings,
            slow_query_threshold=self.slow_query_threshold,
        )
        # Registration happens in QueryCapture.__init__

    def _setup_api(self, include_in_schema: bool) -> None:
        """Mount API endpoints."""
        api_router = create_api_router(self.auth_dependency)
        self.app.include_router(api_router, include_in_schema=include_in_schema)

    def _setup_dashboard(self, include_in_schema: bool) -> None:
        """Mount dashboard static files."""
        from fastapi import Depends, Request
        from fastapi.responses import FileResponse

        dashboard_dir = Path(__file__).parent / "dashboard" / "dist"

        if not dashboard_dir.exists():
            dashboard_dir.mkdir(parents=True, exist_ok=True)
            self._create_placeholder_dashboard(dashboard_dir)
            print("\n" + "=" * 60)
            print("⚠️  FastAPI Radar: Dashboard not built")
            print("=" * 60)
            print("To use the full dashboard, build it with:")
            print("  cd fastapi_radar/dashboard")
            print("  npm install")
            print("  npm run build")
            print("=" * 60 + "\n")

        # Prepare dependencies list for the route
        dependencies = []
        if self.auth_dependency:
            dependencies.append(Depends(self.auth_dependency))

        @self.app.get(
            f"{self.dashboard_path}/{{full_path:path}}",
            include_in_schema=include_in_schema,
            dependencies=dependencies,
        )
        async def serve_dashboard(request: Request, full_path: str = ""):
            if full_path and any(
                full_path.endswith(ext)
                for ext in [
                    ".js",
                    ".css",
                    ".ico",
                    ".png",
                    ".jpg",
                    ".svg",
                    ".woff",
                    ".woff2",
                    ".ttf",
                ]
            ):
                file_path = dashboard_dir / full_path
                if file_path.exists():
                    return FileResponse(file_path)

            index_path = dashboard_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            else:
                return {"error": "Dashboard not found. Please build the dashboard."}

    def _create_placeholder_dashboard(self, dashboard_dir: Path) -> None:
        index_html = dashboard_dir / "index.html"
        index_html.write_text(
            """
<!DOCTYPE html>
<html lang="en" data-theme="{theme}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FastAPI Radar</title>
</head>
<body>
    <div class="container">
        <h1>FastAPI Radar</h1>
        <p>Dashboard not built. Please run npm run build in fastapi_radar/dashboard.</p>
    </div>
</body>
</html>
        """.replace("{theme}", self.theme)
        )

    async def create_tables(self) -> None:
        """Create database tables.

        This assumes Tortoise has been initialized by the application.
        """
        await Tortoise.generate_schemas()

    async def drop_tables(self) -> None:
        """Drop all Radar tables."""
        await Tortoise._drop_databases()

    async def cleanup(self, older_than_hours: Optional[int] = None) -> int:
        from datetime import datetime, timedelta, timezone

        hours = older_than_hours or self.retention_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        deleted_count = await CapturedRequest.filter(created_at__lt=cutoff).delete()
        return deleted_count
