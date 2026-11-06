"""Small operator commands.

    python -m app.cli reset-password <username>

Kept out of the HTTP API on purpose: changing a password is something an
operator does on the server, not something the console may do without proving
the old one.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .db import get_session_factory, init_db
from .models import User
from .security import hash_password


def _reset_password(username: str) -> int:
    init_db()
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"no user named {username!r}", file=sys.stderr)
            return 1
        password = getpass.getpass("new password: ")
        if len(password) < 8:
            print("password must be at least 8 characters", file=sys.stderr)
            return 1
        if password != getpass.getpass("repeat password: "):
            print("passwords do not match", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        session.commit()
    print(f"password updated for {username}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password", help="set a new password for a user")
    reset.add_argument("username")
    args = parser.parse_args(argv)
    if args.command == "reset-password":
        return _reset_password(args.username)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
