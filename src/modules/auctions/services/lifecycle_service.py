"""Auction state transitions and the events they emit."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import AuctionStatus, NotificationType
from src.core.keys import events_key
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.modules.auctions.entities.auction import Auction
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.services.bidding_service import BiddingService
from src.modules.auctions.services.watcher_service import WatcherService
from src.modules.notifications.services.notification_service import NotificationService
from src.modules.users.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuctionLifecycleService:
    def __init__(self, session: AsyncSession, gateway: Gateway, broker: Broker) -> None:
        self._session = session
        self._gateway = gateway
        self._broker = broker
        self._auctions = AuctionRepository(session)
        self._bidding = BiddingService(session, gateway)
        self._watchers = WatcherService(gateway)
        self._notifications = NotificationService(session, broker)
        self._users = UserRepository(session)

    async def activate(self, auction: Auction) -> bool:
        if auction.status != AuctionStatus.scheduled:
            return False

        await self._auctions.set_status(auction, AuctionStatus.active)
        await self._bidding.seed_state(auction, status=AuctionStatus.active.value)
        await self._auctions.commit()

        payload = {
            "auction_id": str(auction.id),
            "title": auction.title,
            "start_time": auction.start_time.isoformat(),
            "end_time": auction.end_time.isoformat(),
            "starting_price": str(auction.starting_price),
            "min_increment": str(auction.min_increment),
        }
        await self._broker.publish(
            events_key(auction.id),
            {
                "type": NotificationType.auction_started.value,
                "auction_id": str(auction.id),
                "data": payload,
            },
        )

        recipients = set(await self._watchers.members(auction.id))
        recipients.add(auction.seller_id)
        for user_id in recipients:
            await self._notifications.notify(
                user_id=user_id,
                type_=NotificationType.auction_started.value,
                payload=payload,
                auction_id=auction.id,
            )
        await self._session.commit()

        logger.info("auction %s started, notified %d user(s)", auction.id, len(recipients))
        return True

    async def finalize(self, auction: Auction) -> bool:
        if auction.status != AuctionStatus.active:
            return False

        await self._auctions.set_status(auction, AuctionStatus.ended)
        await self._bidding.seed_state(auction, status=AuctionStatus.ended.value)
        await self._auctions.commit()

        winner = (
            await self._users.get_by_id(auction.current_winner_id)
            if auction.current_winner_id
            else None
        )
        payload = {
            "auction_id": str(auction.id),
            "title": auction.title,
            "final_price": str(auction.current_price),
            "winner_id": str(auction.current_winner_id) if auction.current_winner_id else None,
            "winner_username": winner.username if winner else None,
        }

        await self._broker.publish(
            events_key(auction.id),
            {
                "type": NotificationType.auction_ended.value,
                "auction_id": str(auction.id),
                "data": payload,
            },
        )

        recipients = set(await self._watchers.members(auction.id))
        recipients.add(auction.seller_id)
        if auction.current_winner_id:
            recipients.add(auction.current_winner_id)
        for user_id in recipients:
            await self._notifications.notify(
                user_id=user_id,
                type_=NotificationType.auction_ended.value,
                payload=payload,
                auction_id=auction.id,
            )
        await self._session.commit()

        logger.info("auction %s ended, winner=%s", auction.id, auction.current_winner_id)
        return True
