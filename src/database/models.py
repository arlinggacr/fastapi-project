"""Single import point that registers every entity on ``Base.metadata``.

Importing this module is what makes ``relationship("User")`` resolvable and
what lets Alembic autogenerate see the full schema. ``session.py`` imports it
for side effects so no caller has to remember to.
"""

from src.database.base import Base
from src.modules.auctions.entities.auction import Auction
from src.modules.auctions.entities.bid import Bid
from src.modules.notifications.entities.notification import Notification
from src.modules.users.entities.user import User

__all__ = ["Auction", "Base", "Bid", "Notification", "User"]
