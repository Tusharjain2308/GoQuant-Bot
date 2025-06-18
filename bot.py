import os
import logging
import asyncio
import httpx
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

from core.arbitrage_monitor import start_monitor_task
from db.session import SessionLocal
from models import TelegramChat, MonitoredSymbol, ArbitrageAlert
from services.gomarket_client import GoMarketClient
from services.arbitrage_service import ArbitrageService
from services.market_view_service import MarketViewService
from collections import defaultdict
import time

gomarket_client = GoMarketClient()
arbitrage_service = None
market_view_service = None

# ---------- Commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if not chat:
            chat = TelegramChat(chat_id=chat_id)
            session.add(chat)
            session.commit()
    finally:
        session.close()

    keyboard = [
        [InlineKeyboardButton("📊 List Symbols", callback_data="list_symbols")],
        [InlineKeyboardButton("🔍 Monitor Arbitrage", callback_data="monitor_arbitrage")],
        [InlineKeyboardButton("📈 Market View", callback_data="market_view")],
        [InlineKeyboardButton("📋 Current Status", callback_data="status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = """
🤖 *Trading Bot Activated*

Welcome to the sophisticated trading information system! 

*Available Features:*
• Arbitrage monitoring across multiple exchanges
• Consolidated market view with CBBO
• Real-time alerts and signals
• Interactive configuration

Use the buttons below to get started:
    """
    await update.message.reply_text(welcome_message, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

async def list_symbols(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exchanges = ["okx", "deribit", "bybit", "binance"]
    keyboard = [[InlineKeyboardButton(f"📋 {ex.upper()}", callback_data=f"symbols_{ex}")] for ex in exchanges]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("🔍 *Select Exchange for Symbol Discovery*", reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.edit_message_text("🔍 *Select Exchange for Symbol Discovery*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def monitor_arb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if len(context.args) < 3:
        await update.message.reply_text(
        "❌ *Invalid Usage*\n\n"
        "Usage: `/monitor_arb <symbol> <exchange1> <exchange2> [threshold_%]`\n\n"
        "ℹ️ *What this does*: Starts real-time arbitrage monitoring for the specified symbol between two exchanges.\n"
        "You’ll receive alerts when the price difference exceeds the given threshold.\n\n"
        "📌 *Example*: `/monitor_arb ETH-USDT binance okx 0.7`\n"
        "→ This will notify you when ETH-USDT price difference between Binance and OKX exceeds 0.7%.\n\n"
        "*Note:* Symbol must be in `BASE-QUOTE` format (e.g., BTC-USDT). Exchange names must be lowercase. Threshold is optional and defaults to 0.5% if not specified.",
        parse_mode=ParseMode.MARKDOWN
    )
        return

    symbol = context.args[0].upper()
    exchange1 = context.args[1].lower()
    exchange2 = context.args[2].lower()
    threshold = float(context.args[3]) if len(context.args) > 3 else 0.5

    session = SessionLocal()
    try:
        session.add_all([
            MonitoredSymbol(symbol=symbol, exchange=exchange1, threshold_percentage=threshold),
            MonitoredSymbol(symbol=symbol, exchange=exchange2, threshold_percentage=threshold)
        ])
        chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.arbitrage_enabled = True
        session.commit()
    finally:
        session.close()

    start_monitor_task(context.bot, chat_id, symbol, exchange1, exchange2, threshold)
    await start_cbbo_reporting_task(context.bot, chat_id, symbol, [exchange1, exchange2])
    await update.message.reply_text(
        f"✅ *Arbitrage Monitoring Started*\n\n"
        f"Symbol: `{symbol}`\n"
        f"Exchanges: `{exchange1}` ↔️ `{exchange2}`\n"
        f"Threshold: `{threshold}%`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard()
    )

async def view_market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if len(context.args) < 1:
        await update.message.reply_text(
        "❌ *Invalid Usage*\n\n"
        "Usage: `/view_market <symbol> [exchange1] [exchange2] ...]`\n\n"
        "ℹ️ *What this does*: Fetches real-time L1 price data (bid/ask) for the given trading pair from selected exchanges.\n\n"
        "📌 *Example*: `/view_market ETH-USDT binance okx bybit`\n"
        "→ This will show the current bid/ask price of ETH-USDT from Binance, OKX, and Bybit.\n\n"
        "*Note:* Symbol format should be `BASE-QUOTE` (e.g., BTC-USDT). Exchange names must be lowercase.",
        parse_mode=ParseMode.MARKDOWN
    )

        return

    symbol = context.args[0].upper()
    exchanges = [ex.lower() for ex in context.args[1:]] or ["okx", "binance", "bybit", "deribit"]

    session = SessionLocal()
    try:
        chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.market_view_enabled = True
            session.commit()
    finally:
        session.close()

    market_data = {}
    for ex in exchanges:
        try:
            data = await gomarket_client.get_l1_orderbook(ex, symbol)
            if data:
                market_data[ex] = data
        except httpx.HTTPStatusError as e:
            logging.error(f"{ex.upper()} {symbol}: HTTP error {e.response.status_code}")
        except Exception as e:
            logging.error(f"{ex.upper()} {symbol}: Unexpected error {e}")

    if not market_data:
        await update.message.reply_text("❌ No market data available.")
        return

    best_bid = max((d.get('bid', 0) for d in market_data.values() if d.get('bid')), default=0)
    best_ask = min((d.get('ask', float('inf')) for d in market_data.values() if d.get('ask')), default=float('inf'))
    mid_price = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask < float('inf') else 0

    msg = f"📊 *Market View: {symbol}*\n🎯 *CBBO Mid Price: ${mid_price:.2f}*\n💰 Bid: ${best_bid:.2f}\n💸 Ask: ${best_ask:.2f}\n\n"
    msg += "*Exchange Details:*\n"
    for ex, d in market_data.items():
        bid = d.get("bid", 0)
        ask = d.get("ask", 0)
        msg += f"• {ex.upper()}: Bid ${bid:.2f} | Ask ${ask:.2f}\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())

# ---------- Callback Handler ----------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logging.info(f"📩 Button clicked: {data}")

    if data == "list_symbols":
        await list_symbols(update, context)

    elif data == "monitor_arbitrage":
        await query.message.edit_text(
        "📡 *Monitor Arbitrage*\n\n"
        "Use this command to monitor real-time arbitrage:\n\n"
        "📌 *Format*: `/monitor_arb <symbol> <exchange1> <exchange2> [threshold_%]`\n"
        "ℹ️ Example: `/monitor_arb BTC-USDT okx deribit 0.8`\n\n"
        "This starts monitoring BTC-USDT between OKX and Deribit and notifies you when arbitrage exceeds 0.8%.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard()
    )

    elif data == "market_view":
        await query.message.edit_text(
        "📊 *View Market Prices*\n\n"
        "Use this command to check live bid/ask across exchanges:\n\n"
        "📌 *Format*: `/view_market <symbol> [exchange1] [exchange2] ...`\n"
        "ℹ️ Example: `/view_market ETH-USDT okx binance deribit`\n\n"
        "This shows ETH-USDT price across OKX, Binance, and Deribit.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard()
    )
    
    elif data.startswith("symbols_"):
        exchange = data.split("_")[1]
        try:
            symbols = await gomarket_client.get_symbols(exchange, "spot")

            if not symbols:
                await query.edit_message_text(
                    f"❌ Could not fetch symbols for {exchange.upper()} at the moment.",
                    reply_markup=main_menu_keyboard()
                )
                return

            # Safely slice the symbols
            top_symbols = symbols[:20]
            msg = f"📋 *Symbols on {exchange.upper()}*\n" + "\n".join(
            f"`{i+1:2d}. {s}`" for i, s in enumerate(top_symbols)
            )
            if len(symbols) > 20:
                msg += "\n... and more"

            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())

        except Exception as e:
            logging.error(f"❌ Error in symbols handler: {e}")
            await query.edit_message_text(
            f"❌ Error while fetching symbols: {e}",
            reply_markup=main_menu_keyboard()
            )

    elif data == "status":
        chat_id = str(query.from_user.id)
        session = SessionLocal()
        try:
            chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
            monitored = session.query(MonitoredSymbol).filter_by(is_active=True).all()
            alerts = session.query(ArbitrageAlert).filter_by(is_active=True).order_by(ArbitrageAlert.timestamp.desc()).limit(5).all()

            msg = f"📊 *Status*\n\n"
            if chat:
                msg += f"🔍 Arbitrage: {'✅' if chat.arbitrage_enabled else '❌'}\n"
                msg += f"📈 Market View: {'✅' if chat.market_view_enabled else '❌'}\n"
            msg += f"📌 Monitors: {len(monitored)}\n🚨 Alerts: {len(alerts)}\n"
            if monitored:
                msg += "\n*Active Monitors:*\n" + "\n".join(f"• {m.symbol} on {m.exchange.upper()}" for m in monitored[:5])
        finally:
            session.close()

        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())

    elif data == "cbbo":
        await query.message.edit_text(
            "🧠 *CBBO (Consolidated Best Bid/Offer)*\n\n"
            "This command gives you the best bid and best ask price for a symbol across multiple exchanges.\n\n"
            "📌 *Format*: `/get_cbbo <symbol> [exchange1] [exchange2] ...`\n"
            "ℹ️ Example: `/get_cbbo BTC-USDT okx deribit`\n\n"
            "If you don’t mention exchanges, all supported ones will be used by default.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard()
        )   

    elif data == "stop":
        await stop(update, context)

    elif data == "reset":
        await reset(update, context)

# ---------- Cbbo Commands ----------
async def cbbo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if query:
            await query.answer()
            await query.edit_message_text("⏳ Fetching CBBO, Mid-price, and Best Venues...")
        else:
            await update.message.reply_text("⏳ Fetching CBBO, Mid-price, and Best Venues...")

        symbol = "BTC-USDT"
        exchanges = ["okx", "binance", "bybit", "deribit"]

        result = await market_view_service.get_cbbo_and_mid(symbol, exchanges)

        if not result or "cbbo" not in result:
            msg = "❌ Could not compute CBBO."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
            return

        cbbo = result["cbbo"]
        mid_price = result["mid_price"]
        venue_bbo = result["venue_bbo"]
        best_bid_venue = result["best_bid_venue"]
        best_ask_venue = result["best_ask_venue"]

        message = f"📊 *CBBO View for* `{symbol}`\n\n"
        message += f"🔵 *Best Bid:* `{cbbo['best_bid']}`\n"
        message += f"🔴 *Best Ask:* `{cbbo['best_ask']}`\n"
        message += f"📈 *Mid Price:* `{mid_price}`\n\n"
        if best_bid_venue:
            message += f"🏆 *Best Bid Venue:* `{best_bid_venue.upper()}`\n"
        if best_ask_venue:
            message += f"🥇 *Best Ask Venue:* `{best_ask_venue.upper()}`\n"
        message += "\n🏦 *Per Exchange BBOs:*\n"
        for ex, bbo in venue_bbo.items():
            bid = bbo["bid"] if bbo["bid"] is not None else "N/A"
            ask = bbo["ask"] if bbo["ask"] is not None else "N/A"
            message += f"• `{ex.upper()}` → 🟦 `{bid}` / 🟥 `{ask}`\n"

        if query:
            await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard())

    except Exception as e:
        logging.error(f"❌ Error in cbbo_handler: {e}")
        msg = "Something went wrong while fetching CBBO."
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg)

# ---------- Stop and Reset Commands ----------
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.arbitrage_enabled = False
            chat.market_view_enabled = False
            session.commit()
    finally:
        session.close()

    msg = "⛔ *All services stopped.*\nYou can use the menu below to start again."

    if update.message:
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = SessionLocal()
    try:
        session.query(MonitoredSymbol).delete()
        session.query(ArbitrageAlert).delete()
        chat = session.query(TelegramChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.arbitrage_enabled = False
            chat.market_view_enabled = False
        session.commit()
    finally:
        session.close()

    msg = "🔄 *All data reset successfully.*\nStart fresh using the menu below."

    if update.message:
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode=ParseMode.MARKDOWN)

latest_cbbo_message_ids = defaultdict(lambda: None)
previous_cbbo_values = {}

async def start_cbbo_reporting_task(bot, chat_id: str, symbol: str, exchanges: list[str]):
    global previous_cbbo_values, latest_cbbo_message_ids

    async def report_cbbo():
        while True:
            try:
                result = await market_view_service.get_cbbo_and_mid(symbol, exchanges)
                if not result:
                    await bot.send_message(chat_id=chat_id, text=f"❌ Could not fetch CBBO for {symbol}.")
                    return

                cbbo = result["cbbo"]
                mid_price = result["mid_price"]
                venue_bbo = result["venue_bbo"]
                best_bid_venue = result["best_bid_venue"]
                best_ask_venue = result["best_ask_venue"]

                # Build message content
                message_text = f"📡 *Live CBBO Report: `{symbol}`*\n\n"
                message_text += f"🔵 *Best Bid:* `${cbbo['best_bid']}` on `{best_bid_venue.upper()}`\n"
                message_text += f"🔴 *Best Ask:* `${cbbo['best_ask']}` on `{best_ask_venue.upper()}`\n"
                message_text += f"📈 *CBBO Mid Price:* `${mid_price:.2f}`\n\n"
                message_text += "🏦 *Per Exchange Prices:*\n"
                for ex, bbo in venue_bbo.items():
                    bid = bbo["bid"] if bbo["bid"] is not None else "N/A"
                    ask = bbo["ask"] if bbo["ask"] is not None else "N/A"
                    message_text += f"• `{ex.upper()}` → 🟦 `${bid}` / 🟥 `${ask}`\n"

                prev_data = previous_cbbo_values.get(chat_id)
                if prev_data != message_text:
                    # First-time or update
                    previous_cbbo_values[chat_id] = message_text
                    msg_id = latest_cbbo_message_ids[chat_id]

                    if msg_id:
                        try:
                            await bot.edit_message_text(
                                text=message_text,
                                chat_id=chat_id,
                                message_id=msg_id,
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as e:
                            logging.warning(f"Edit message failed: {e}")
                            msg = await bot.send_message(chat_id=chat_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
                            latest_cbbo_message_ids[chat_id] = msg.message_id
                    else:
                        msg = await bot.send_message(chat_id=chat_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
                        latest_cbbo_message_ids[chat_id] = msg.message_id

            except Exception as e:
                logging.error(f"[CBBO Loop] Error: {e}")

            await asyncio.sleep(10)  # polling interval

    asyncio.create_task(report_cbbo())


# ---------- Menu Commands ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 List Symbols", callback_data="list_symbols")],
        [InlineKeyboardButton("🔍 Monitor Arbitrage", callback_data="monitor_arbitrage")],
        [InlineKeyboardButton("📈 Market View", callback_data="market_view")],
        [InlineKeyboardButton("🧠 Get CBBO", callback_data="cbbo")],
        [InlineKeyboardButton("📋 Current Status", callback_data="status")],
        [InlineKeyboardButton("⛔ Stop All", callback_data="stop")],
        [InlineKeyboardButton("🔄 Reset", callback_data="reset")]
    ])

# ---------- Main Entrypoint ----------
def main():
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("❌ TELEGRAM_BOT_TOKEN missing.")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list_symbols", list_symbols))
    application.add_handler(CommandHandler("monitor_arb", monitor_arb_command))
    application.add_handler(CommandHandler("view_market", view_market_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CommandHandler("get_cbbo", cbbo_command))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("reset", reset))

    global arbitrage_service, market_view_service
    arbitrage_service = ArbitrageService(application.bot)
    market_view_service = MarketViewService(application.bot)

    async def setup_services():
        await arbitrage_service.start()
        await market_view_service.start()

    import threading
    threading.Thread(target=lambda: asyncio.run(setup_services()), daemon=True).start()

    logging.info("🚀 Bot started. Listening for events...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
