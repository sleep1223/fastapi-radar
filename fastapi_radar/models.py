"""Storage models for FastAPI Radar."""

from tortoise import fields, models


class CapturedRequest(models.Model):
    id = fields.IntField(pk=True)
    request_id = fields.CharField(max_length=36, unique=True, index=True)
    method = fields.CharField(max_length=10)
    url = fields.CharField(max_length=500)
    path = fields.CharField(max_length=500)
    query_params = fields.JSONField(null=True)
    headers = fields.JSONField(null=True)
    body = fields.TextField(null=True)
    status_code = fields.IntField(null=True)
    response_body = fields.TextField(null=True)
    response_headers = fields.JSONField(null=True)
    duration_ms = fields.FloatField(null=True)
    client_ip = fields.CharField(max_length=50, null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    queries: fields.ReverseRelation["CapturedQuery"]
    exceptions: fields.ReverseRelation["CapturedException"]

    class Meta:
        table = "radar_requests"


class CapturedQuery(models.Model):
    id = fields.IntField(pk=True)
    request: fields.ForeignKeyRelation[CapturedRequest] = fields.ForeignKeyField("models.CapturedRequest", related_name="queries", to_field="request_id", source_field="request_id", null=True, on_delete=fields.CASCADE)
    sql = fields.TextField()
    parameters = fields.JSONField(null=True)
    duration_ms = fields.FloatField(null=True)
    rows_affected = fields.IntField(null=True)
    connection_name = fields.CharField(max_length=100, null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "radar_queries"


class CapturedException(models.Model):
    id = fields.IntField(pk=True)
    request: fields.ForeignKeyRelation[CapturedRequest] = fields.ForeignKeyField("models.CapturedRequest", related_name="exceptions", to_field="request_id", source_field="request_id", null=True, on_delete=fields.CASCADE)
    exception_type = fields.CharField(max_length=100)
    exception_value = fields.TextField(null=True)
    traceback = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "radar_exceptions"


class Trace(models.Model):
    trace_id = fields.CharField(max_length=32, pk=True)
    service_name = fields.CharField(max_length=100, index=True, null=True)
    operation_name = fields.CharField(max_length=200, null=True)
    start_time = fields.DatetimeField(auto_now_add=True, index=True)
    end_time = fields.DatetimeField(null=True)
    duration_ms = fields.FloatField(null=True)
    span_count = fields.IntField(default=0)
    status = fields.CharField(max_length=20, default="ok")
    tags = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    spans: fields.ReverseRelation["Span"]

    class Meta:
        table = "radar_traces"


class Span(models.Model):
    span_id = fields.CharField(max_length=16, pk=True)
    trace: fields.ForeignKeyRelation[Trace] = fields.ForeignKeyField("models.Trace", related_name="spans", to_field="trace_id")
    parent_span_id = fields.CharField(max_length=16, index=True, null=True)
    operation_name = fields.CharField(max_length=200)
    service_name = fields.CharField(max_length=100, index=True, null=True)
    span_kind = fields.CharField(max_length=20, default="server")
    start_time = fields.DatetimeField(index=True)
    end_time = fields.DatetimeField(null=True)
    duration_ms = fields.FloatField(null=True)
    status = fields.CharField(max_length=20, default="ok")
    tags = fields.JSONField(null=True)
    logs = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "radar_spans"


class SpanRelation(models.Model):
    id = fields.IntField(pk=True)
    trace_id = fields.CharField(max_length=32, index=True)
    parent_span_id = fields.CharField(max_length=16, index=True)
    child_span_id = fields.CharField(max_length=16, index=True)
    depth = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "radar_span_relations"


class BackgroundTask(models.Model):
    id = fields.IntField(pk=True)
    task_id = fields.CharField(max_length=36, unique=True, index=True)
    request_id = fields.CharField(max_length=36, index=True, null=True)
    name = fields.CharField(max_length=200)
    status = fields.CharField(max_length=20, default="pending", index=True)
    start_time = fields.DatetimeField(index=True, null=True)
    end_time = fields.DatetimeField(null=True)
    duration_ms = fields.FloatField(null=True)
    error = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True, index=True)

    class Meta:
        table = "radar_background_tasks"
