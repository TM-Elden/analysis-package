"""`ap-auth` admin CLI - user/session/service-token administration.

No admin screens exist until a later phase (design doc section 5.1/5.2), so this is the only way to
provision the users table `ap_api`'s real login/bearer auth reads from.

    ap-auth adduser <id> --display-name NAME --roles analyst,reviewer [--password PW]
    ap-auth passwd <id> [--password PW]
    ap-auth disable <id>
    ap-auth enable <id>
    ap-auth token <id> [--ttl-days N]      # issue a service-account bearer token
    ap-auth list

`--password` is accepted for scripting/CI provisioning; omit it to be prompted interactively
(`getpass`, never echoed, never in shell history). `--db PATH` / `AP_AUTH_DB` override the default
auth DB location (`ap_auth.store.DEFAULT_AUTH_DB`) - same default `ap_api/deps.py::get_auth_store`
resolves, so a freshly-provisioned user is immediately visible to the running API without extra
wiring.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import sys
from pathlib import Path

from ap_auth.identity import IdentityError, parse_roles
from ap_auth.roles import Role
from ap_auth.store import DEFAULT_AUTH_DB, AuthError, AuthStore


def _db_path(args: argparse.Namespace) -> Path:
    if args.db:
        return Path(args.db)
    return Path(os.environ.get("AP_AUTH_DB", str(DEFAULT_AUTH_DB)))


def _read_password(args: argparse.Namespace, *, prompt: str) -> str:
    if args.password:
        return args.password
    pw1 = getpass.getpass(prompt)
    pw2 = getpass.getpass("Confirm: ")
    if pw1 != pw2:
        print("passwords do not match", file=sys.stderr)
        raise SystemExit(2)
    if not pw1:
        print("password must be non-empty", file=sys.stderr)
        raise SystemExit(2)
    return pw1


def _cmd_adduser(args: argparse.Namespace) -> int:
    try:
        roles = parse_roles(args.roles)
    except IdentityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    password = None
    if not args.no_password:
        password = _read_password(args, prompt=f"Password for {args.user_id}: ")
    with AuthStore(_db_path(args)) as store:
        try:
            store.create_user(args.user_id, display_name=args.display_name, roles=roles, password=password)
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"created user {args.user_id!r} (roles: {args.roles})")
    return 0


def _cmd_passwd(args: argparse.Namespace) -> int:
    password = _read_password(args, prompt=f"New password for {args.user_id}: ")
    with AuthStore(_db_path(args)) as store:
        try:
            store.set_password(args.user_id, password)
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"password updated for {args.user_id!r}")
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    with AuthStore(_db_path(args)) as store:
        try:
            store.set_disabled(args.user_id, True)
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"disabled {args.user_id!r} (all outstanding sessions/tokens revoked)")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    with AuthStore(_db_path(args)) as store:
        try:
            store.set_disabled(args.user_id, False)
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print(f"enabled {args.user_id!r}")
    return 0


def _cmd_token(args: argparse.Namespace) -> int:
    kwargs = {"ttl": dt.timedelta(days=args.ttl_days)} if args.ttl_days else {}
    with AuthStore(_db_path(args)) as store:
        try:
            raw = store.create_service_token(args.user_id, **kwargs)
        except AuthError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    print("service-account bearer token (shown once - store it now):")
    print(raw)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    with AuthStore(_db_path(args)) as store:
        users = store.list_users()
    if not users:
        print("(no users)")
        return 0
    for u in users:
        flags = []
        if u.disabled:
            flags.append("disabled")
        if not u.has_password:
            flags.append("no-password (service account only)")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"{u.id}\t{u.display_name}\troles={u.roles}{flag_str}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ap-auth", description="fathm C11 user/session administration")
    parser.add_argument("--db", help="auth DB path (default: $AP_AUTH_DB or ~/.fathm/auth.sqlite3)")
    sub = parser.add_subparsers(dest="command", required=True)

    known_roles = ", ".join(r.value for r in Role)

    p = sub.add_parser("adduser", help="create a user")
    p.add_argument("user_id")
    p.add_argument("--display-name", required=True)
    p.add_argument("--roles", required=True, help=f"comma-separated, from: {known_roles}")
    p.add_argument("--password", help="set non-interactively (else prompted); omit with --no-password")
    p.add_argument("--no-password", action="store_true", help="service-account-only user (bearer tokens, no login)")
    p.set_defaults(func=_cmd_adduser)

    p = sub.add_parser("passwd", help="set/reset a user's password")
    p.add_argument("user_id")
    p.add_argument("--password", help="set non-interactively (else prompted)")
    p.set_defaults(func=_cmd_passwd)

    p = sub.add_parser("disable", help="disable a user (blocks login; revokes their sessions/tokens)")
    p.add_argument("user_id")
    p.set_defaults(func=_cmd_disable)

    p = sub.add_parser("enable", help="re-enable a disabled user")
    p.add_argument("user_id")
    p.set_defaults(func=_cmd_enable)

    p = sub.add_parser("token", help="issue a service-account bearer token (Authorization: Bearer <token>)")
    p.add_argument("user_id")
    p.add_argument("--ttl-days", type=int, default=None, help="default: 365 days")
    p.set_defaults(func=_cmd_token)

    p = sub.add_parser("list", help="list users")
    p.set_defaults(func=_cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
