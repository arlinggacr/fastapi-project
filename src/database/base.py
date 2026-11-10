"""Declarative base only.

Kept dependency-free so entities can import it without cycles. Entity
registration happens in :mod:`src.database.models`.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every module entity."""
