"""
Phase 5.1 + 5.2 - Telegram broadcasting & Admin Hub.

  python telegram_distribute.py                # posts pending deals to channel + X copy to admin chat
  python telegram_distribute.py --dry-run      # print what WOULD be sent, touch nothing
  python telegram_distribute.py --admin-only   # only the private admin report (X copy)

Env variables (add them to .env):
  TELEGRAM_BOT_TOKEN      token from @BotFather
  TELEGRAM_CHAT_ID        public channel / group to broadcast the deals to
  TELEGRAM_ADMIN_CHAT_ID  (optional) private chat that receives the X copy
"""

import argparse
import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

from database import SessionLocal
from crud import get_pending_deals, update_deal_status
from deals_format import format_deal_message, x_copy_text

load_dotenv()

PENDING_LIMIT = 50


def _require_env(*names):
    return [name for name in names if not (os.getenv(name) or "").strip()]


def _get_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and add "
            "the token to .env (see SETUP.md)."
        )
    return Bot(token=token)


async def _post_to_channel(bot, chat_id, deal) -> bool:
    """Posts one deal; tries photo + caption, falls back to plain text."""
    caption = format_deal_message(deal)
    if deal.image_url:
        try:
            await bot.send_photo(chat_id=chat_id, photo=deal.image_url, caption=caption)
            return True
        except Exception as exc:
            print(f"    image send failed ({exc}), retrying as text")
    try:
        await bot.send_message(chat_id=chat_id, text=caption)
        return True
    except Exception as exc:
        print(f"    text send failed: {exc}")
        return False


async def broadcast_pending(bot, chat_id, admin_chat_id, dry_run, admin_only=False) -> tuple:
    published = 0
    sent_admin = 0

    db = SessionLocal()
    try:
        pending = get_pending_deals(db, limit=PENDING_LIMIT)
        if not pending:
            print("  no pending deals.")
            return 0, 0

        for deal in pending:
            msg = format_deal_message(deal)

            if not admin_only:
                if dry_run:
                    print("\n  [DRY] would post to channel:")
                    print("  " + msg.replace("\n", "\n  "))
                    published += 1
                else:
                    print(f"\n  posting {deal.product_id}...")
                    if await _post_to_channel(bot, chat_id, deal):
                        update_deal_status(db, deal.id, "published")
                        published += 1
                    else:
                        continue

            if admin_chat_id:
                copy = x_copy_text(deal)
                if dry_run:
                    print("\n  [DRY] would send X copy to admin chat:")
                    print("  " + copy.replace("\n", "\n  "))
                    sent_admin += 1
                else:
                    try:
                        await bot.send_message(chat_id=admin_chat_id, text=copy)
                        sent_admin += 1
                    except Exception as exc:
                        print(f"    admin copy send failed: {exc}")
        return published, sent_admin
    finally:
        db.close()


def run_broadcast(dry_run=False, admin_only=False) -> tuple:
    missing = _require_env("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    if missing and not dry_run:
        raise RuntimeError(
            f"missing env: {', '.join(missing)}. Add them to .env (see SETUP.md)."
        )

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    bot = _get_bot() if not (dry_run and not os.getenv("TELEGRAM_BOT_TOKEN")) else None

    print("Telegram broadcast (DRY RUN)" if dry_run else "Telegram broadcast (LIVE)")
    print(f"  channel chat id : {chat_id}")
    print(f"  admin chat id   : {admin_chat_id or 'unset (X copy skipped)'}")

    return asyncio.run(
        broadcast_pending(
            bot, chat_id, admin_chat_id,
            dry_run=dry_run, admin_only=admin_only,
        )
    )


def main():
    parser = argparse.ArgumentParser(description="Telegram broadcaster + Admin Hub")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--admin-only", action="store_true")
    args = parser.parse_args()

    published, admin_sent = run_broadcast(dry_run=args.dry_run, admin_only=args.admin_only)
    print(f"\nDONE: {published} deals published, {admin_sent} admin copies sent.")


if __name__ == "__main__":
    main()