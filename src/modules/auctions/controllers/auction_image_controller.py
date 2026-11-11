"""Auction image routes: /auctions/{auction_id}/images"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.storage import S3Storage
from src.database.session import get_session
from src.modules.auctions.dtos.image_response import AuctionImageResponse
from src.modules.auctions.services.image_service import AuctionImageService
from src.modules.users.entities.user import User
from src.utils.deps import get_current_user, get_storage
from src.utils.responses import SuccessEnvelope, success

router = APIRouter(prefix="/auctions/{auction_id}/images", tags=["auction images"])


@router.post(
    "",
    response_model=SuccessEnvelope[list[AuctionImageResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def upload_images(
    auction_id: UUID,
    files: list[UploadFile] = File(
        ...,
        description=(
            "One or more image files (JPEG, PNG, GIF, WebP). Send a single file "
            "to upload one image, or repeat the field for a batch."
        ),
    ),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: S3Storage = Depends(get_storage),
) -> dict[str, Any]:
    images = await AuctionImageService(session, storage).upload(auction_id, user, files)
    return success(images, f"{len(images)} image(s) uploaded")


@router.get("", response_model=SuccessEnvelope[list[AuctionImageResponse]])
async def list_images(
    auction_id: UUID,
    session: AsyncSession = Depends(get_session),
    storage: S3Storage = Depends(get_storage),
) -> dict[str, Any]:
    images = await AuctionImageService(session, storage).list(auction_id)
    return success(images, "Images retrieved")


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(
    auction_id: UUID,
    image_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: S3Storage = Depends(get_storage),
) -> None:
    await AuctionImageService(session, storage).delete(auction_id, image_id, user)
