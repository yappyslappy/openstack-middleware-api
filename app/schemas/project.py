from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema, SourceIdentitySchema


class ProjectSchema(Schema):
    id = fields.String(required=True)
    name = fields.String(required=True)
    description = fields.String(allow_none=True)
    enabled = fields.Boolean(allow_none=True)
    domain_id = fields.String(allow_none=True)
    inventory_source = fields.Nested(SourceIdentitySchema, required=True)


class ProjectCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(ProjectSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)
