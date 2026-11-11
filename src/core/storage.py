"""S3-compatible object storage (Filebase).

An object's canonical address is ``{public base}/{key}``, and that is what is
persisted on the row. Whether that address is *readable* depends on the bucket:
Filebase only serves buckets publicly on a paid plan. So
:meth:`S3Storage.access_url` returns either the canonical URL or a time-limited
presigned one, controlled by ``S3_PUBLIC_READ``.

Writes still need credentials, which is why the upload path is guarded by
:attr:`Settings.storage_configured`.

``boto3`` is synchronous, so every network call is pushed to a worker thread
with :func:`asyncio.to_thread`. That keeps the event loop free without adding
``aiobotocore`` and a second client stack.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from src.core.config import Settings

logger = logging.getLogger(__name__)

# S3 accepts at most 1000 keys per delete_objects call.
DELETE_BATCH_SIZE = 1000


class StorageError(Exception):
    """Raised when the object store cannot fulfil a request."""


class S3Storage:
    """Thin wrapper around the handful of S3 operations the API needs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None
        self._lock = asyncio.Lock()

    # -- configuration -------------------------------------------------------
    @property
    def configured(self) -> bool:
        return self._settings.storage_configured

    @property
    def bucket(self) -> str:
        return self._settings.s3_resolved_bucket

    def url_for(self, key: str) -> str:
        """Public URL for an object key."""
        return f"{self._settings.s3_public_base}/{key.lstrip('/')}"

    def build_key(self, *, folder: str, filename: str) -> str:
        """Object key under the configured prefix, e.g. ``auction/<folder>/<uuid>.png``."""
        prefix = self._settings.s3_prefix.strip("/")
        folder = folder.strip("/")
        return f"{prefix}/{folder}/{filename}" if folder else f"{prefix}/{filename}"

    # -- client --------------------------------------------------------------
    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._create_client)
        return self._client

    def _create_client(self) -> Any:
        if not self.configured:
            raise StorageError(
                "Object storage is not configured. Set S3_ACCESS_TOKEN and "
                "S3_SECRET_KEY (S3_URL supplies the bucket and public base)."
            )
        return boto3.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            region_name=self._settings.region,
            aws_access_key_id=self._settings.s3_access_token,
            aws_secret_access_key=self._settings.s3_secret_key,
            config=BotoConfig(
                signature_version=self._settings.signature_version,
                # Filebase speaks path-style addressing.
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    # -- operations ----------------------------------------------------------
    async def put(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        cache_control: str = "public, max-age=31536000, immutable",
    ) -> str:
        """Upload bytes and return the public URL."""
        client = await self._get_client()

        def _put() -> None:
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl=cache_control,
            )

        try:
            await asyncio.to_thread(_put)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("s3 put failed for key %s", key)
            raise StorageError("Could not store the uploaded file") from exc
        return self.url_for(key)

    async def delete(self, key: str) -> None:
        """Remove an object. Missing keys are treated as already deleted."""
        client = await self._get_client()

        def _delete() -> None:
            client.delete_object(Bucket=self.bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("s3 delete failed for key %s", key)
            raise StorageError("Could not delete the stored file") from exc

    async def delete_many(self, keys: list[str]) -> None:
        """Remove several objects, best effort.

        Used when an auction is deleted and its images go with it. One failed
        object must not stop the rest from being cleaned up, so errors are
        logged rather than raised.
        """
        if not keys:
            return
        client = await self._get_client()

        def _delete_batch(batch: list[str]) -> None:
            client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )

        for start in range(0, len(keys), DELETE_BATCH_SIZE):
            batch = keys[start : start + DELETE_BATCH_SIZE]
            try:
                await asyncio.to_thread(_delete_batch, batch)
            except (BotoCoreError, ClientError):
                logger.exception("s3 batch delete failed for %d keys", len(batch))

    async def presigned_url(self, key: str, *, expires_in: int | None = None) -> str:
        """Time-limited read URL.

        Filebase requires a paid plan for truly public buckets, so this is how
        an object stays reachable without one.
        """
        client = await self._get_client()
        ttl = expires_in or self._settings.s3_presign_ttl_seconds

        def _sign() -> str:
            return str(
                client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=ttl,
                )
            )

        try:
            return await asyncio.to_thread(_sign)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("s3 presign failed for key %s", key)
            raise StorageError("Could not sign the file URL") from exc

    async def access_url(self, key: str) -> str:
        """The URL a client should use right now for this key."""
        if self._settings.s3_public_read:
            return self.url_for(key)
        return await self.presigned_url(key)
