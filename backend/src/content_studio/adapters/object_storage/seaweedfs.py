import asyncio
from functools import partial

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from content_studio.config import Settings


class SeaweedFSObjectStorage:
    """S3-compatible adapter targeting SeaweedFS's S3 gateway. boto3 is
    synchronous, so every call — including the one-time bucket check — is
    pushed to a thread via asyncio.to_thread to keep the FastAPI event loop
    unblocked. This adapter is swapped for a real S3/R2/B2 client in
    production without touching application code, per the mandated
    ports-and-adapters pattern.

    Explicit region + short timeouts + capped retries: boto3 defaults
    (unbounded-feeling retry/backoff, and newer SDK versions' default
    request-checksum headers) can hang for a long time against a
    non-AWS S3-compatible endpoint like SeaweedFS instead of failing fast."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.object_storage_bucket
        boto_config = BotoConfig(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
            region_name="us-east-1",
            config=boto_config,
        )
        # Presigned URLs from self._client would carry the Docker-internal
        # endpoint above, unreachable from a browser — a second client,
        # identical except for its endpoint_url, generates URLs the browser
        # can actually fetch. Same client (and object_storage_public_endpoint
        # left empty) when there's no separate public endpoint, e.g. local dev.
        public_endpoint = settings.object_storage_public_endpoint or settings.object_storage_endpoint
        self._presign_client = (
            self._client
            if public_endpoint == settings.object_storage_endpoint
            else boto3.client(
                "s3",
                endpoint_url=public_endpoint,
                aws_access_key_id=settings.object_storage_access_key,
                aws_secret_access_key=settings.object_storage_secret_key,
                region_name="us-east-1",
                config=boto_config,
            )
        )
        self._bucket_ready = False

    def _ensure_bucket_sync(self) -> None:
        if self._bucket_ready:
            return
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self._bucket not in existing:
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except ClientError as exc:
                # A fresh client instance's list_buckets() isn't guaranteed
                # to reflect a bucket created moments ago by a different
                # client instance (each Temporal activity builds its own
                # SeaweedFSObjectStorage) — treat "someone already created
                # it" as success rather than a real failure.
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        self._bucket_ready = True

    async def _ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket_sync)

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        await self._ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get_presigned_url(self, *, key: str, expires_in_seconds: int = 3600) -> str:
        return await asyncio.to_thread(
            partial(
                self._presign_client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
        )

    async def delete_object(self, *, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
