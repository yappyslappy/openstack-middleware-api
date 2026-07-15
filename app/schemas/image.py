from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema, SourceIdentitySchema


class ImageSchema(Schema):
    id = fields.String(required=True)
    name = fields.String(required=True)
    status = fields.String(allow_none=True)
    visibility = fields.String(allow_none=True)
    container_format = fields.String(allow_none=True)
    disk_format = fields.String(allow_none=True)
    min_disk = fields.Integer(allow_none=True)
    min_ram = fields.Integer(allow_none=True)
    size_bytes = fields.Integer(allow_none=True)
    checksum = fields.String(allow_none=True)
    created_at = fields.String(allow_none=True)
    updated_at = fields.String(allow_none=True)
    inventory_source = fields.Nested(SourceIdentitySchema, required=True)


class ImageCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(ImageSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)
