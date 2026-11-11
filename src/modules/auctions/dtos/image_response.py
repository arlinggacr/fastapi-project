from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuctionImageResponse(BaseModel):
    """An uploaded image.

    ``key`` and ``url`` are exactly what is stored in the database: the object
    key inside the bucket and its canonical public address.

    ``access_url`` is the address to fetch the file from right now. When the
    bucket is not public (Filebase requires a paid plan for that) it is a
    time-limited presigned URL; otherwise it equals ``url``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auction_id: UUID
    key: str
    url: str
    access_url: str
    content_type: str
    size_bytes: int
    position: int
    created_at: datetime
