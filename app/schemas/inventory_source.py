from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema


class InventorySourceSchema(Schema):
    id = fields.Integer(required=True)
    scope = fields.String(required=True)
    openstack_project_id = fields.String(allow_none=True)
    openstack_project_name = fields.String(allow_none=True)
    region_name = fields.String(allow_none=True)
    last_successful_sync_at = fields.String(allow_none=True)
    last_failed_sync_at = fields.String(allow_none=True)


class InventorySourceCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(InventorySourceSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)
