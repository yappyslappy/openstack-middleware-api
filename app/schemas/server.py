from __future__ import annotations

from marshmallow import Schema, fields

from app.schemas.common import CountMetaSchema, SourceIdentitySchema


class ServerSchema(Schema):
    id = fields.String(required=True)
    name = fields.String(required=True)
    status = fields.String(allow_none=True)
    project_id = fields.String(allow_none=True)
    flavor = fields.String(allow_none=True)
    image = fields.String(allow_none=True)
    addresses = fields.Dict(
        keys=fields.String(),
        values=fields.List(fields.Dict(keys=fields.String(), values=fields.Raw())),
        required=True,
    )
    tags = fields.List(fields.String(), required=True)
    created_at = fields.String(allow_none=True)
    updated_at = fields.String(allow_none=True)
    inventory_source = fields.Nested(SourceIdentitySchema, required=True)


class ServerCollectionResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.List(fields.Nested(ServerSchema), required=True)
    meta = fields.Nested(CountMetaSchema, required=True)


class ServerResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "success"})
    data = fields.Nested(ServerSchema, required=True)
