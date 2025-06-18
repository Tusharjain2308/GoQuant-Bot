# core/arbitrage_monitor.py
import asyncio
import logging
from typing import Dict
from telegram import Bot
from services.gomarket_client import gomarket_client
import time
import logging
from telegram.constants import ParseMode
from services.market_view_service import MarketViewService

# Keep track of active background tasks
active_tasks: Dict[str, Dict[str, asyncio.Task]] = {}

async def monitor_arbitrage_task(bot: Bot, chat_id: str, symbol: str, ex1: str, ex2: str, threshold: float):
    while True:
        try:
            orderbooks = await gomarket_client.get_multiple_orderbooks([
                (symbol, ex1),
                (symbol, ex2),
            ])
            ob1 = orderbooks.get(f"{ex1}_{symbol}")
            ob2 = orderbooks.get(f"{ex2}_{symbol}")

            if ob1 and ob2 and ob1["ask"] and ob2["bid"]:
                ask_price = ob1["ask"]
                bid_price = ob2["bid"]
                spread = ((bid_price - ask_price) / ask_price) * 100

                if spread >= threshold:
                    msg = (
                        f"📢 *Arbitrage Opportunity Detected!*\n\n"
                        f"Symbol: `{symbol}`\n"
                        f"{ex1.upper()} Ask: `${ask_price:.2f}`\n"
                        f"{ex2.upper()} Bid: `${bid_price:.2f}`\n"
                        f"📈 Spread: `{spread:.2f}%` (Threshold: {threshold}%)"
                    )
                    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"⚠️ Background monitor error for {symbol}: {e}")

        await asyncio.sleep(10)  # Sleep before next check

def start_monitor_task(bot: Bot, chat_id: str, symbol: str, ex1: str, ex2: str, threshold: float):
    if chat_id not in active_tasks:
        active_tasks[chat_id] = {}

    task_key = f"{symbol}_{ex1}_{ex2}"

    # Avoid duplicate tasks
    if task_key in active_tasks[chat_id]:
        logging.info(f"🔁 Task already running for {task_key}")
        return

    task = asyncio.create_task(
        monitor_arbitrage_task(bot, chat_id, symbol, ex1, ex2, threshold)
    )
    active_tasks[chat_id][task_key] = task

async def monitor_symbol_for_arb(symbol, exchanges, threshold_pct, chat_id, context):
    last_signal = {}
    message_id = None
    last_sent_time = 0

    while True:
        try:
            result = await MarketViewService.get_cbbo_and_mid(symbol, exchanges)
            cbbo = result["cbbo"]
            mid_price = result["mid_price"]
            best_bid = cbbo["best_bid"]
            best_ask = cbbo["best_ask"]
            best_bid_venue = result["best_bid_venue"]
            best_ask_venue = result["best_ask_venue"]

            spread_pct = ((best_bid - best_ask) / best_ask) * 100 if best_ask else 0

            if (
                best_bid_venue != last_signal.get("bid_venue") or
                best_ask_venue != last_signal.get("ask_venue") or
                abs(mid_price - last_signal.get("mid_price", 0)) > 1
            ):
                text = (
                    f"📡 *{symbol} Live Signal*\n\n"
                    f"🏆 *Best Bid:* `{best_bid}` on `{best_bid_venue.upper()}`\n"
                    f"🥇 *Best Ask:* `{best_ask}` on `{best_ask_venue.upper()}`\n"
                    f"📈 *Mid Price:* `{mid_price}`\n"
                    f"📊 *Spread %:* `{spread_pct:.2f}%`"
                )

                try:
                    if message_id:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        msg = await context.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                        message_id = msg.message_id

                    last_signal = {
                        "bid_venue": best_bid_venue,
                        "ask_venue": best_ask_venue,
                        "mid_price": mid_price,
                    }
                    last_sent_time = time.time()

                except Exception as e:
                    logging.error(f"🔴 Error sending/editing venue signal: {e}")

            await asyncio.sleep(5)

        except Exception as e:
            logging.error(f"⚠️ Monitoring error for {symbol}: {e}")
            await asyncio.sleep(10)