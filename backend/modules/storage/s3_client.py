"""S3 helper for call recording upload and retrieval.

Credentials are resolved in order:
  1. EC2 IAM role (auto-discovered by boto3 — no config needed)
  2. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in settings / .env

All objects are stored **private**. Use :meth:`S3RecordingClient.presigned_url`
to generate a time-limited GET URL for the frontend.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError

from common.logging import get_logger
from config.settings import settings

log = get_logger("storage.s3")


class S3RecordingClient:
    """Thin async-friendly wrapper around boto3 S3 for audio recordings."""

    def __init__(self) -> None:
        kwargs: dict[str, Any] = {"region_name": settings.AWS_REGION}
        if settings.AWS_ACCESS_KEY_ID:
            kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        if settings.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
        self._client = boto3.client("s3", **kwargs)
        self._bucket = settings.S3_RECORDINGS_BUCKET

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_from_url(
        self,
        source_url: str,
        s3_key: str,
        *,
        twilio_account_sid: str | None = None,
        twilio_auth_token: str | None = None,
        content_type: str = "audio/mpeg",
    ) -> str:
        """Download ``source_url`` (with optional Twilio basic-auth) and PUT to S3.

        Returns the S3 key on success.  Raises on download or upload failure.
        """
        auth = None
        if twilio_account_sid and twilio_auth_token:
            auth = (twilio_account_sid, twilio_auth_token)

        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.get(source_url, auth=auth)
            resp.raise_for_status()
            audio_bytes = resp.content

        return await self.upload_bytes(
            audio_bytes, s3_key, content_type=content_type
        )

    async def upload_bytes(
        self,
        data: bytes,
        s3_key: str,
        content_type: str = "audio/mpeg",
    ) -> str:
        """Upload raw bytes to S3. Returns the S3 key."""

        def _put() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)
        log.info("storage.s3.uploaded", key=s3_key, bucket=self._bucket, size=len(data))
        return s3_key

    # ------------------------------------------------------------------
    # Presigned URL
    # ------------------------------------------------------------------

    def presigned_url(self, s3_key: str, expires: int | None = None) -> str:
        """Return a time-limited HTTPS GET URL for ``s3_key``.

        ``expires`` defaults to ``settings.S3_PRESIGNED_URL_EXPIRES`` (1 hour).
        """
        ttl = expires if expires is not None else settings.S3_PRESIGNED_URL_EXPIRES
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": s3_key},
                ExpiresIn=ttl,
            )
            return url
        except ClientError:
            log.exception("storage.s3.presign_failed", key=s3_key)
            raise

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, s3_key: str) -> None:
        """Delete an object from S3 (best-effort — logs on failure)."""

        def _del() -> None:
            self._client.delete_object(Bucket=self._bucket, Key=s3_key)

        try:
            await asyncio.to_thread(_del)
            log.info("storage.s3.deleted", key=s3_key)
        except ClientError:
            log.exception("storage.s3.delete_failed", key=s3_key)


@lru_cache(maxsize=1)
def get_s3_client() -> S3RecordingClient:
    """Process-wide singleton — safe to call repeatedly."""
    return S3RecordingClient()
