import argparse
import asyncio
import getpass
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from pydantic import TypeAdapter
from pydantic import ValidationError

from core.security import hash_password
from db.session import AsyncSessionLocal
from db.session import close_database_connections
from models.user import AccountStatus
from models.user import UserRole
from repositories import users
from schemas.auth_schema import NormalizedEmail
from schemas.auth_schema import StrongPassword

email_adapter = TypeAdapter(NormalizedEmail)
password_adapter = TypeAdapter(StrongPassword)


def parse_args():
    parser = argparse.ArgumentParser(description="Create or update a bootstrap admin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Promote/reactivate an existing user and reset their password.",
    )

    return parser.parse_args()


def read_password() -> str:
    password = os.getenv("ADMIN_PASSWORD")

    if password is not None:
        return password

    password = getpass.getpass("Password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if password != confirm_password:
        raise ValueError("Passwords do not match")

    return password


async def create_admin(email: str, first_name: str, last_name: str, password: str, force: bool) -> str:
    async with AsyncSessionLocal() as db:
        existing_user = await users.get_by_email(db, email, for_update=True)

        if existing_user and not force:
            raise ValueError(
                "User already exists. Re-run with FORCE=true to promote/reactivate "
                "and reset the password."
            )

        try:
            if existing_user:
                existing_user.first_name = first_name.strip()
                existing_user.last_name = last_name.strip()
                existing_user.password_hash = hash_password(password)
                existing_user.role_enum = UserRole.ADMIN
                existing_user.status_enum = AccountStatus.ACTIVE
                await db.flush()
                await db.commit()

                return "Updated existing user as active admin"

            users.create(
                db,
                first_name=first_name,
                last_name=last_name,
                email=email,
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                status=AccountStatus.ACTIVE,
            )
            await db.commit()

            return "Created active admin user"
        except Exception:
            await db.rollback()
            raise


async def main() -> int:
    args = parse_args()

    try:
        email = str(email_adapter.validate_python(args.email))
        password = password_adapter.validate_python(read_password())
        first_name = args.first_name.strip()
        last_name = args.last_name.strip()

        if not first_name or not last_name:
            raise ValueError("First and last name are required")

        message = await create_admin(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
            force=args.force,
        )
    except (ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        await close_database_connections()

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
