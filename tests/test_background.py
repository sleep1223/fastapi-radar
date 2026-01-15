"""Tests for background task tracking."""

import asyncio

import pytest
from fastapi_radar.background import track_background_task
from fastapi_radar.models import BackgroundTask


@pytest.mark.unit
@pytest.mark.asyncio
class TestBackgroundTaskTracking:
    """Test background task tracking decorator."""

    async def test_track_sync_task_ignored(self, db):
        """Test that sync tasks are NOT tracked (Tortoise limitation/design choice)."""

        @track_background_task()
        def sync_task(value):
            return value * 2

        result = sync_task(21)

        assert result == 42

        # Verify task was NOT tracked
        count = await BackgroundTask.all().count()
        assert count == 0

    async def test_track_async_task_success(self, db):
        """Test tracking a successful async task."""

        @track_background_task()
        async def async_task(value):
            await asyncio.sleep(0.01)
            return value * 2

        result = await async_task(21)

        assert result == 42

        # Verify task was tracked
        tasks = await BackgroundTask.all()
        assert len(tasks) == 1
        assert tasks[0].name == "async_task"
        assert tasks[0].status == "completed"
        assert tasks[0].duration_ms >= 10  # At least 10ms due to sleep

    async def test_track_async_task_failure(self, db):
        """Test tracking a failed async task."""

        @track_background_task()
        async def failing_async_task():
            await asyncio.sleep(0.01)
            raise RuntimeError("Async task failed")

        with pytest.raises(RuntimeError, match="Async task failed"):
            await failing_async_task()

        # Verify task was tracked as failed
        tasks = await BackgroundTask.all()
        assert len(tasks) == 1
        assert tasks[0].name == "failing_async_task"
        assert tasks[0].status == "failed"
        assert tasks[0].error == "Async task failed"

    async def test_track_task_with_request_id(self, db):
        """Test tracking a task with request_id."""

        @track_background_task()
        async def task_with_request():
            return "done"

        # Call with request_id
        result = await task_with_request(_radar_request_id="request-123")

        assert result == "done"

        # Verify task has request_id
        tasks = await BackgroundTask.all()
        assert len(tasks) == 1
        assert tasks[0].request_id == "request-123"

    async def test_track_task_without_request_id(self, db):
        """Test tracking a task without request_id."""

        @track_background_task()
        async def independent_task():
            return "done"

        result = await independent_task()

        assert result == "done"

        # Verify task has no request_id
        tasks = await BackgroundTask.all()
        assert len(tasks) == 1
        assert tasks[0].request_id is None

    async def test_task_timing(self, db):
        """Test that task timing is recorded correctly."""

        @track_background_task()
        async def timed_task():
            await asyncio.sleep(0.05)  # 50ms
            return "done"

        await timed_task()

        tasks = await BackgroundTask.all()
        assert len(tasks) == 1
        assert tasks[0].duration_ms >= 50
        assert tasks[0].start_time is not None
        assert tasks[0].end_time is not None
        assert tasks[0].end_time > tasks[0].start_time

    async def test_multiple_tasks(self, db):
        """Test tracking multiple tasks."""

        @track_background_task()
        async def task_a():
            return "a"

        @track_background_task()
        async def task_b():
            return "b"

        await task_a()
        await task_b()
        await task_a()

        tasks = await BackgroundTask.all()
        assert len(tasks) == 3

        task_names = [t.name for t in tasks]
        assert task_names.count("task_a") == 2
        assert task_names.count("task_b") == 1

    async def test_task_unique_ids(self, db):
        """Test that each task gets a unique ID."""

        @track_background_task()
        async def repeated_task():
            return "done"

        await repeated_task()
        await repeated_task()
        await repeated_task()

        tasks = await BackgroundTask.all()
        assert len(tasks) == 3

        task_ids = [t.task_id for t in tasks]
        assert len(set(task_ids)) == 3  # All unique
