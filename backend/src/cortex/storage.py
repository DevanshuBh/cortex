"""Object storage through the S3 API only (SeaweedFS locally, Amazon S3 on AWS) — switching is configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from cortex.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def object_key(tenant_id: str, document_id: str, filename: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:200] or "document"
    return f"tenants/{tenant_id}/documents/{document_id}/{safe}"


def _client(endpoint: str | None) -> S3Client:
    s = get_settings()
    kwargs: dict[str, Any] = {
        "region_name": s.s3_region,
        "config": Config(
            signature_version="s3v4", s3={"addressing_style": "path"}, retries={"max_attempts": 3}
        ),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs["aws_access_key_id"] = s.s3_access_key.get_secret_value()
        kwargs["aws_secret_access_key"] = s.s3_secret_key.get_secret_value()
    return boto3.client("s3", **kwargs)


@lru_cache
def s3() -> S3Client:
    return _client(get_settings().s3_endpoint_url)


@lru_cache
def s3_public() -> S3Client:
    """Client whose presigned URLs point at the endpoint the browser can reach."""
    s = get_settings()
    return _client(s.s3_public_endpoint_url or s.s3_endpoint_url)


def ensure_bucket() -> None:
    client, bucket = s3(), get_settings().s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=bucket)


def presign_put(key: str, content_type: str, expires: int = 900) -> str:
    return s3_public().generate_presigned_url(
        "put_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    s3().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType=content_type)


def get_bytes(key: str) -> bytes:
    return s3().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def head(key: str) -> int | None:
    client = s3()
    try:
        return int(client.head_object(Bucket=get_settings().s3_bucket, Key=key)["ContentLength"])
    except client.exceptions.ClientError:
        return None


def delete(key: str) -> None:
    s3().delete_object(Bucket=get_settings().s3_bucket, Key=key)
