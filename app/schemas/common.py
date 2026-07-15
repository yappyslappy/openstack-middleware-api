from __future__ import annotations

from marshmallow import Schema, fields


class CountMetaSchema(Schema):
    count = fields.Integer(required=True, metadata={"example": 185})


class ErrorResponseSchema(Schema):
    status = fields.String(required=True, metadata={"example": "error"})
    message = fields.String(required=True, metadata={"example": "Description"})
    code = fields.Integer(required=True, metadata={"example": 400})


class SourceIdentitySchema(Schema):
    id = fields.Integer(allow_none=True)
    scope = fields.String(required=True)
    project_id = fields.String(allow_none=True)
    project_name = fields.String(allow_none=True)
    region_name = fields.String(allow_none=True)


class AddressSchema(Schema):
    addr = fields.String(required=True)
    version = fields.Integer(allow_none=True)
    address_type = fields.String(
        attribute="OS-EXT-IPS:type",
        data_key="OS-EXT-IPS:type",
        allow_none=True,
    )
    mac_address = fields.String(
        attribute="OS-EXT-IPS-MAC:mac_addr",
        data_key="OS-EXT-IPS-MAC:mac_addr",
        allow_none=True,
    )
