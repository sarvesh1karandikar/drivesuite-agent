"""
DriveSuite — Main entry point.

Initialises the aiogram Dispatcher and Bot, registers handlers,
and starts long-polling.
"""

from __future__ import annotations

import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from bot.handlers import router as handlers_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("drivesuite")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_IDS_STR = os.environ.get("ALLOWED_TELEGRAM_IDS", "")
ADMIN_IDS_STR = os.environ.get("ADMIN_TELEGRAM_IDS", "")

if not BOT_TOKEN:
    log.error("TELEGRAM_BOT_TOKEN is not set. Create a .env file or export it.")
    sys.exit(1)


def _parse_int_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


ALLOWED_TELEGRAM_IDS = _parse_int_list(ALLOWED_IDS_STR)
ADMIN_TELEGRAM_IDS = _parse_int_list(ADMIN_IDS_STR)

# ---------------------------------------------------------------------------
# Dispatcher & Bot
# ---------------------------------------------------------------------------

dp = Dispatcher()
dp.include_router(handlers_router)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)

# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------


async def _on_startup() -> None:
    me = await bot.get_me()
    log.info("")
    log.info("╔═══════════════════════════════════════════════╗")
    log.info("║          DriveSuite Agent is online           ║")
    log.info(f"║  Bot: @{me.username}                          ║")
    log.info("╚═══════════════════════════════════════════════╝")
    log.info("")
    if ALLOWED_TELEGRAM_IDS:
        log.info("Allowed users: %s", ALLOWED_TELEGRAM_IDS)
    if ADMIN_TELEGRAM_IDS:
        log.info("Admins: %s", ADMIN_TELEGRAM_IDS)


dp.startup.register(_on_startup)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Start polling."""
    log.info("Starting DriveSuite Agent ...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
