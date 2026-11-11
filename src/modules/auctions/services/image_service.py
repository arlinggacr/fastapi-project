"""Image upload use-cases.

Files are validated by their magic bytes rather than the declared content
type, so renaming ``payload.exe`` to ``photo.png`` is rejected. Accepted bytes
are written to the bucket under ``{prefix}/{auction_id}/<uuid><ext>`` and the
resulting key **and** canonical URL are stored on the row.

The first image by position doubles as the auction's cover: ``image_url`` is
kept in sync so existing clients that read a single image keep working.
"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.responses import ApiError, forbidden, not_found
from src.core.config import get_settings
from src.core.storage import S3Storage, StorageError
from src.modules.auctions.dtos.image_response import AuctionImageResponse
from src.modules.auctions.entities.auction import Auction
from src.modules.auctions.entities.auction_image import AuctionImage
from src.modules.auctions.repositories.auction_image_repository import (
    AuctionImageRepository,
)
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.users.entities.user import User

logger = logging.getLogger(__name__)

# Magic-byte signatures -> canonical content type.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# WEBP is "RIFF" + 4 size bytes + "WEBP".
_WEBP_MAGIC = b"WEBP"
_RIFF_MAGIC = b"RIFF"

READ_CHUNK = 64 * 1024
# Bounded so one request cannot fan out into an unbounded number of objects.
MAX_FILES_PER_REQUEST = 10


def sniff_image_type(head: bytes) -> str | None:
    """Return the real content type of an image payload, or ``None``."""
    for signature, content_type in _SIGNATURES:
        if head.startswith(signature):
            return content_type
    if head.startswith(_RIFF_MAGIC) and head[8:12] == _WEBP_MAGIC:
        return "image/webp"
    return None


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload, aborting as soon as it exceeds ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(
                413,
                "IMAGE_TOO_LARGE",
                f"Each image must be {max_bytes // (1024 * 1024)} MiB or smaller",
            )
        chunks.append(chunk)
    return b"".join(chunks)


class AuctionImageService:
    def __init__(
        self,
        session: AsyncSession,
        storage: S3Storage,
    ) -> None:
        self._session = session
        self._storage = storage
        self._images = AuctionImageRepository(session)
        self._auctions = AuctionRepository(session)

    # -- upload --------------------------------------------------------------
    async def upload(
        self,
        auction_id: UUID,
        user: User,
        files: list[UploadFile],
    ) -> list[AuctionImageResponse]:
        """Upload one or more images for an auction.

        The same endpoint serves a single file and a batch; both arrive as a
        list. All files are validated before anything is written, so a bad
        file in the batch does not leave half an upload behind.
        """
        if not files:
            raise ApiError(400, "NO_FILES", "At least one image is required")
        if len(files) > MAX_FILES_PER_REQUEST:
            raise ApiError(
                400,
                "TOO_MANY_FILES",
                f"At most {MAX_FILES_PER_REQUEST} images can be uploaded at once",
            )

        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        self._assert_can_manage(auction, user)

        if not self._storage.configured:
            raise ApiError(
                503,
                "STORAGE_NOT_CONFIGURED",
                "Image uploads are not configured on this server",
            )

        settings = get_settings()
        max_bytes = settings.s3_max_image_bytes

        prepared: list[tuple[bytes, str, str]] = []
        for upload in files:
            payload = await _read_limited(upload, max_bytes)
            if not payload:
                raise ApiError(400, "EMPTY_FILE", "Uploaded file is empty")

            content_type = sniff_image_type(payload[:16])
            if content_type is None:
                raise ApiError(
                    415,
                    "UNSUPPORTED_IMAGE",
                    "Only JPEG, PNG, GIF and WebP images are supported",
                )
            prepared.append((payload, content_type, _EXTENSIONS[content_type]))

        position = await self._images.next_position(auction_id)
        stored: list[AuctionImage] = []
        for payload, content_type, extension in prepared:
            key = self._storage.build_key(
                folder=str(auction_id),
                filename=f"{uuid.uuid4().hex}{extension}",
            )
            try:
                url = await self._storage.put(
                    key=key, data=payload, content_type=content_type
                )
            except StorageError:
                await self._rollback_uploaded(stored)
                raise ApiError(
                    502, "STORAGE_ERROR", "Could not store the uploaded file"
                ) from None

            try:
                image = await self._images.create(
                    auction_id=auction_id,
                    key=key,
                    url=url,
                    content_type=content_type,
                    size_bytes=len(payload),
                    position=position,
                )
            except SQLAlchemyError:
                # The object is already in the bucket but has no row; drop it
                # so a failed insert does not leave an orphan behind.
                await self._delete_quietly(key)
                await self._rollback_uploaded(stored)
                raise
            stored.append(image)
            position += 1

        await self._sync_cover(auction)
        await self._images.commit()

        return [await self._to_response(image) for image in stored]

    # -- reads ---------------------------------------------------------------
    async def list(self, auction_id: UUID) -> list[AuctionImageResponse]:
        if await self._auctions.get_by_id(auction_id) is None:
            raise not_found("Auction")
        images = await self._images.list_for_auction(auction_id)
        return [await self._to_response(image) for image in images]

    # -- delete --------------------------------------------------------------
    async def delete(self, auction_id: UUID, image_id: UUID, user: User) -> None:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        self._assert_can_manage(auction, user)

        image = await self._images.get_by_id(image_id)
        if image is None or image.auction_id != auction_id:
            raise not_found("Image")

        try:
            await self._storage.delete(image.key)
        except StorageError:
            # The object may already be gone; the row still has to disappear.
            logger.warning("continuing after failed s3 delete for %s", image.key)

        await self._images.delete(image)
        await self._sync_cover(auction)
        await self._images.commit()

    async def purge_objects(self, auction_id: UUID) -> None:
        """Remove every stored object for an auction, leaving the rows alone.

        Called just before the auction itself is deleted: the image rows go
        with it via ``ON DELETE CASCADE``, but the objects in the bucket would
        otherwise be orphaned.
        """
        keys = await self._images.list_keys(auction_id)
        if not keys:
            return
        try:
            await self._storage.delete_many(keys)
        except StorageError:
            logger.warning("could not purge %d objects for auction %s", len(keys), auction_id)

    # -- helpers -------------------------------------------------------------
    async def _to_response(self, image: AuctionImage) -> AuctionImageResponse:
        """Attach the URL the client can actually fetch right now."""
        try:
            access_url = await self._storage.access_url(image.key)
        except StorageError:
            logger.warning("could not sign %s; falling back to stored url", image.key)
            access_url = image.url

        return AuctionImageResponse(
            id=image.id,
            auction_id=image.auction_id,
            key=image.key,
            url=image.url,
            access_url=access_url,
            content_type=image.content_type,
            size_bytes=image.size_bytes,
            position=image.position,
            created_at=image.created_at,
        )

    async def _rollback_uploaded(self, stored: list[AuctionImage]) -> None:
        """Best-effort cleanup when a batch fails midway."""
        for image in stored:
            await self._delete_quietly(image.key)

    async def _delete_quietly(self, key: str) -> None:
        """Delete an object, logging instead of raising on failure."""
        try:
            await self._storage.delete(key)
        except StorageError:
            logger.warning("cleanup could not delete %s", key)

    async def _sync_cover(self, auction: Auction) -> None:
        """Point ``auction.image_url`` at the lowest-position image."""
        images = await self._images.list_for_auction(auction.id)
        auction.image_url = images[0].url if images else None
        await self._session.flush()

    @staticmethod
    def _assert_can_manage(auction: Auction, user: User) -> None:
        if auction.seller_id != user.id and not user.is_admin:
            raise forbidden("Only the seller or an admin can manage these images")
