"""Shared enums.

Kept in ``common`` so entities, DTOs and services all reference one
definition instead of duplicating literals.
"""

from enum import StrEnum


class UserRole(StrEnum):
    user = "user"
    admin = "admin"


class AuctionStatus(StrEnum):
    scheduled = "scheduled"
    active = "active"
    ended = "ended"
    cancelled = "cancelled"


class NotificationType(StrEnum):
    auction_started = "auction_started"
    auction_ended = "auction_ended"
    outbid = "outbid"
    bid_placed = "bid_placed"
