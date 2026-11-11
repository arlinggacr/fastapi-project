"""Pydantic models for the response envelopes.

These exist so ``response_model=`` can describe the real wire format in the
OpenAPI schema. They mirror the dictionaries built in
:mod:`src.utils.responses.handler`.

The ``pagination`` keys keep the original camelCase spelling (``totalData``,
``totalPage``) to stay byte-compatible with the C# implementation.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PaginationMeta(BaseModel):
    """Pagination metadata: ``{totalData, totalPage, page}``."""

    model_config = ConfigDict(populate_by_name=True)

    total_data: int = Field(alias="totalData")
    total_page: int = Field(alias="totalPage")
    page: int


class SuccessEnvelope(BaseModel, Generic[T]):
    """``{status: true, data, message, pagination}``."""

    status: bool = True
    data: T | None = None
    message: str
    pagination: PaginationMeta | None = None


class ErrorEnvelope(BaseModel):
    """``{status: false, message, error}``."""

    status: bool = False
    message: str
    error: Any = None
