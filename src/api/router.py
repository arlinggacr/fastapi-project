"""Route aggregation.

Each module owns its routes; this file only mounts them on the app so there
is a single place to see the public surface.
"""

from fastapi import APIRouter

from src.modules.admin.controllers.admin_controller import router as admin_router
from src.modules.auctions.controllers.auction_controller import router as auction_router
from src.modules.auctions.controllers.auction_image_controller import (
    router as auction_image_router,
)
from src.modules.auctions.controllers.auction_ws_controller import (
    router as auction_ws_router,
)
from src.modules.auth.controllers.auth_controller import router as auth_router
from src.modules.notifications.controllers.notification_controller import (
    router as notification_router,
)
from src.modules.notifications.controllers.notification_ws_controller import (
    router as notification_ws_router,
)
from src.modules.users.controllers.user_controller import router as user_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(user_router)
api_router.include_router(auction_router)
api_router.include_router(auction_image_router)
api_router.include_router(notification_router)
api_router.include_router(admin_router)

ws_router = APIRouter()
ws_router.include_router(auction_ws_router)
ws_router.include_router(notification_ws_router)

__all__ = ["api_router", "ws_router"]
