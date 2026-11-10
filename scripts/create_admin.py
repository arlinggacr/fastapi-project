"""Promote a user to admin, or create one.

Usage:
    .venv/bin/python scripts/create_admin.py --email admin@example.com \
        --username admin --password 'S3curePassw0rd!'

If the user already exists it is promoted instead of duplicated.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.constants.enums import UserRole
from src.database.session import SessionLocal
from src.modules.users.repositories.user_repository import UserRepository
from src.utils.security import hash_password


async def main(email: str, username: str, password: str) -> None:
    async with SessionLocal() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(email)

        if user is None:
            user = await repo.create(
                email=email,
                username=username,
                hashed_password=hash_password(password),
                role=UserRole.admin,
            )
            await repo.commit()
            print(f"created admin {user.email} ({user.id})")
            return

        await repo.set_role(user, UserRole.admin)
        await repo.commit()
        print(f"promoted {user.email} to admin ({user.id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.email, args.username, args.password))
