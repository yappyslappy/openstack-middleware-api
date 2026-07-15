from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema, SourceIdentitySchema


class NetworkSchema(Schema):
    id = fields.String(required=True)
    name = fields.String(required=True)
    status = fields.String(allow_none=True)
    project_id = fields.String(allow_none=True)
    mtu = fields.Integer(allow_none=True)
    admin_state_up = fields.Boolean(allow_none=True)
    is_shared = fields.Boolean(allow_none=True)
    is_router_external = fields.Boolean(allow_none=True)
    provider_network_type = fields.String(allow_none=True)
    provider_physical_network = fields.String(allow_none=True)
    provider_segmentation_id = fields.Integer(allow_none=True)
    created_at = fields.String(allow_none=True)
    updated_at = fields.String(allow_none=True)
    inventory_source = fields.Nested(SourceIdentitySchema, required=True)


class NetworkCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(NetworkSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)
