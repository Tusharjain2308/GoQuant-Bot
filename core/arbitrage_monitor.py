# core/arbitrage_monitor.py

import asyncio
import logging
from typing import Dict
from telegram import Bot
from services.gomarket_client import gomarket_client

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
