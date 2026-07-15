from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema, SourceIdentitySchema


class FlavorSchema(Schema):
    id = fields.String(required=True)
    name = fields.String(required=True)
    vcpus = fields.Integer(allow_none=True)
    ram_mb = fields.Integer(allow_none=True)
    disk_gb = fields.Integer(allow_none=True)
    ephemeral_gb = fields.Integer(allow_none=True)
    swap_mb = fields.Integer(allow_none=True)
    is_public = fields.Boolean(allow_none=True)
    created_at = fields.String(allow_none=True)
    updated_at = fields.String(allow_none=True)
    inventory_source = fields.Nested(SourceIdentitySchema, required=True)


class FlavorCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(FlavorSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)
