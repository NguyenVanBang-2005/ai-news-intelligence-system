"""Create the first admin account, or promote an existing account to admin.

The password is never taken from the command line: it is read with getpass (asked
twice), or from AINIS_NEW_ADMIN_PASSWORD for non-interactive runs. It is never printed.

Examples (from the repo root, or inside the API container):
    python scripts/create_admin.py --username alice
    python scripts/create_admin.py --username alice --reset-password
    docker exec -it ainis_main-api-1 python scripts/create_admin.py --username alice
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db.session import get_session_factory  # noqa: E402
from app.services.auth import create_or_promote_admin  # noqa: E402

PASSWORD_ENV_VAR = "AINIS_NEW_ADMIN_PASSWORD"


def read_password() -> str:
    """The password from AINIS_NEW_ADMIN_PASSWORD, else typed twice without echo."""
    from_env = os.environ.get(PASSWORD_ENV_VAR)
    if from_env:
        return from_env
    first = getpass.getpass("New password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise ValueError("passwords do not match")
    return first


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or promote an AINIS admin account.")
    parser.add_argument("--username", required=True, help="account name (3-32: a-z 0-9 _ . -)")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="also set a new password when the account already exists",
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    session_factory: sessionmaker[Session] | None = None,
    password_reader: Callable[[], str] = read_password,
) -> int:
    """Run the command; returns the process exit code (0 ok, 1 invalid input)."""
    args = parse_args(argv)
    factory = session_factory or get_session_factory()
    try:
        with factory() as db:
            outcome = create_or_promote_admin(
                db, args.username, password_reader, reset_password=args.reset_password
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Admin '{args.username.strip().lower()}' {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
