"""Comandi di manutenzione da console.

Uso: docker compose exec config-api python -m app.cli reset-2fa
"""
import argparse
import asyncio
import sys

from app.admin_2fa import reset_totp
from app.database import AsyncSessionLocal


async def _reset_2fa() -> int:
    async with AsyncSessionLocal() as db:
        deleted = await reset_totp(db)
    if deleted:
        print("2FA admin azzerato: al prossimo login verrà richiesta una nuova attivazione.")
    else:
        print("Nessun 2FA admin configurato: niente da fare.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset-2fa", help="Azzera il TOTP dell'admin (es. telefono perso)")
    args = parser.parse_args(argv)
    if args.command == "reset-2fa":
        return asyncio.run(_reset_2fa())
    return 1


if __name__ == "__main__":
    sys.exit(main())
