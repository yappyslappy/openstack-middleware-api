from __future__ import annotations

from marshmallow import Schema, fields


class HealthDataSchema(Schema):
    application = fields.String(required=True)
    database = fields.String(required=True)
    active_inventory_sources = fields.Integer(required=True)
    stale_inventory_sources = fields.Integer(required=True)
    stale_inventory_scopes = fields.List(fields.String(), required=True)
    failed_inventory_sources = fields.Integer(required=True)
    failed_inventory_scopes = fields.List(fields.String(), required=True)
    oldest_successful_sync_at = fields.String(allow_none=True)
    newest_successful_sync_at = fields.String(allow_none=True)


class HealthResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.Nested(HealthDataSchema, required=True)
