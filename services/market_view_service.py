import asyncio
import logging
import httpx
from datetime import datetime
from typing import Dict, List

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    Bot = None
    ParseMode = None
    TELEGRAM_AVAILABLE = False

from models import TelegramChat, MarketData
from services.gomarket_client import GoMarketClient
from db.session import SessionLocal


class MarketViewService:
    """Service for providing consolidated market view and venue signaling"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.gomarket_client = GoMarketClient()
        self.is_running = False
        self.update_interval = 30  # seconds
        self.message_cache = {}  # Cache message IDs for editing

    async def start(self):
        """Start the market view service"""
        self.is_running = True
        logging.info("Market view service started")

        while self.is_running:
            try:
                await self.update_market_data()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                logging.error(f"Error in market view service: {e}")
                await asyncio.sleep(self.update_interval)

    def stop(self):
        """Stop the market view service"""
        self.is_running = False
        logging.info("Market view service stopped")

    async def update_market_data(self):
        """Update market data and send notifications"""
        session = SessionLocal()
        try:
            active_chats = session.query(TelegramChat).filter_by(
                is_active=True,
                market_view_enabled=True
            ).all()

            if not active_chats:
                return

            symbols_to_monitor = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            exchanges = ["okx", "binance", "bybit", "deribit"]

            for symbol in symbols_to_monitor:
                await self._update_symbol_data(symbol, exchanges, active_chats)
        except Exception as e:
            logging.error(f"Error fetching active chats: {e}")
        finally:
            session.close()

    async def _update_symbol_data(self, symbol: str, exchanges: List[str], chats: List):
        """Update data for a specific symbol"""
        session = SessionLocal()
        try:
            market_data = {}
            for exchange in exchanges:
                data = await self.gomarket_client.get_l1_orderbook(exchange, symbol)
                if data and data.get('bid') and data.get('ask'):
                    market_data[exchange] = data

                    # Store in DB
                    market_record = MarketData(
                        symbol=symbol,
                        exchange=exchange,
                        best_bid=data['bid'],
                        best_ask=data['ask'],
                        bid_size=data.get('bid_size'),
                        ask_size=data.get('ask_size')
                    )
                    session.add(market_record)

            session.commit()

            if len(market_data) < 2:
                return

            signals = self._calculate_venue_signals(symbol, market_data)

            if signals:
                await self._send_market_update(symbol, signals, chats)

        except Exception as e:
            session.rollback()
            logging.error(f"Error updating market data for {symbol}: {e}")
        finally:
            session.close()

    def _calculate_venue_signals(self, symbol: str, market_data: Dict) -> Dict:
        """Calculate venue signals and CBBO"""
        try:
            best_bid_data = max(market_data.items(), key=lambda x: x[1]['bid'])
            best_ask_data = min(market_data.items(), key=lambda x: x[1]['ask'])

            best_bid_exchange = best_bid_data[0]
            best_bid_price = best_bid_data[1]['bid']

            best_ask_exchange = best_ask_data[0]
            best_ask_price = best_ask_data[1]['ask']

            mid_price = (best_bid_price + best_ask_price) / 2
            spread = best_ask_price - best_bid_price
            spread_pct = (spread / mid_price) * 100 if mid_price > 0 else 0

            return {
                'symbol': symbol,
                'best_bid_exchange': best_bid_exchange,
                'best_bid_price': best_bid_price,
                'best_ask_exchange': best_ask_exchange,
                'best_ask_price': best_ask_price,
                'mid_price': mid_price,
                'spread': spread,
                'spread_pct': spread_pct,
                'timestamp': datetime.now(),
                'market_data': market_data
            }

        except Exception as e:
            logging.error(f"Error calculating venue signals: {e}")
            return None

    async def _send_market_update(self, symbol: str, signals: Dict, chats: List):
        """Send market update to active chats"""
        try:
            message = self._format_market_message(signals)

            for chat in chats:
                try:
                    chat_key = f"{chat.chat_id}_{symbol}"
                    if chat_key in self.message_cache:
                        try:
                            await self.bot.edit_message_text(
                                chat_id=chat.chat_id,
                                message_id=self.message_cache[chat_key],
                                text=message,
                                parse_mode=ParseMode.MARKDOWN
                            )
                            continue
                        except Exception:
                            pass  # If edit fails, fallback to sending new

                    sent = await self.bot.send_message(
                        chat_id=chat.chat_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    self.message_cache[chat_key] = sent.message_id

                except Exception as e:
                    logging.error(f"Failed to send market update to chat {chat.chat_id}: {e}")

        except Exception as e:
            logging.error(f"Error sending market update: {e}")
            
    # async def get_cbbo_and_mid(self, symbol: str, exchanges: List[str]) -> Dict:
    #     """Returns CBBO, mid-price, and per-exchange BBO."""
    #     best_bid = 0.0
    #     best_ask = float("inf")
    #     venue_bbo = {}

    #     for ex in exchanges:
    #         formatted_symbol = self._format_symbol(ex, symbol)
    #         l2 = await self.gomarket_client.get_l2_orderbook(ex, formatted_symbol)

    #         if not l2:
    #             logging.warning(f"⚠️ Skipping {ex}: No L2 data for {symbol}")
    #             continue

    #         try:
    #             top_bid = l2["bids"][0][0] if l2["bids"] else None
    #             top_ask = l2["asks"][0][0] if l2["asks"] else None

    #             if top_bid:
    #                 best_bid = max(best_bid, top_bid)
    #             if top_ask:
    #                 best_ask = min(best_ask, top_ask)

    #             venue_bbo[ex] = {
    #                 "bid": top_bid,
    #                 "ask": top_ask
    #             }

    #         except Exception as e:
    #             logging.error(f"❌ Error in processing {ex} L2 data: {e}")
    #             continue

    #     mid_price = None
    #     if best_bid > 0 and best_ask < float("inf"):
    #         mid_price = round((best_bid + best_ask) / 2, 4)

    #     return {
    #         "cbbo": {"best_bid": best_bid, "best_ask": best_ask},
    #         "mid_price": mid_price,
    #         "venue_bbo": venue_bbo
    #     }

    async def get_cbbo_and_mid(self, symbol: str, exchanges: List[str]) -> Dict:
        """Returns CBBO, mid-price, best venues, and per-exchange BBO."""
        best_bid = 0.0
        best_ask = float("inf")
        best_bid_venue = None
        best_ask_venue = None
        venue_bbo = {}

        for ex in exchanges:
            formatted_symbol = self._format_symbol(ex, symbol)
            l2 = await self.gomarket_client.get_l2_orderbook(ex, formatted_symbol)

            if not l2:
                logging.warning(f"⚠️ Skipping {ex}: No L2 data for {symbol}")
                continue

            try:
                top_bid = l2["bids"][0][0] if l2["bids"] else None
                top_ask = l2["asks"][0][0] if l2["asks"] else None

                if top_bid is not None:
                    if top_bid > best_bid:
                        best_bid = top_bid
                        best_bid_venue = ex

                if top_ask is not None:
                    if top_ask < best_ask:
                        best_ask = top_ask
                        best_ask_venue = ex

                venue_bbo[ex] = {"bid": top_bid, "ask": top_ask}

            except Exception as e:
                logging.error(f"❌ Error in processing {ex} L2 data: {e}")
                continue

        mid_price = None
        if best_bid > 0 and best_ask < float("inf"):
            mid_price = round((best_bid + best_ask) / 2, 4)

        return {
            "cbbo": {"best_bid": best_bid, "best_ask": best_ask},
            "mid_price": mid_price,
            "venue_bbo": venue_bbo,
            "best_bid_venue": best_bid_venue,
            "best_ask_venue": best_ask_venue
        }

    def _format_symbol(self, exchange: str, symbol: str) -> str:
        # Adjusts for exchange-specific symbol format
        if exchange in ["binance", "bybit"]:
            return symbol.replace("-", "")  # BTC-USDT → BTCUSDT
        return symbol

    def _format_market_message(self, signals: Dict) -> str:
        """Format market signals as Telegram message"""
        timestamp = signals['timestamp'].strftime('%H:%M:%S UTC')

        message = f"📊 *Market View: {signals['symbol']}*\n\n"
        message += f"🎯 *CBBO Mid Price:* `${signals['mid_price']:.4f}`\n"
        message += f"📏 *Spread:* `{signals['spread_pct']:.3f}%` (${signals['spread']:.4f})\n\n"
        message += f"💰 *Best Bid:* `${signals['best_bid_price']:.4f}` on **{signals['best_bid_exchange'].upper()}**\n"
        message += f"💸 *Best Ask:* `${signals['best_ask_price']:.4f}` on **{signals['best_ask_exchange'].upper()}**\n\n"
        message += "*📈 All Exchange Prices:*\n"

        for exchange, data in signals['market_data'].items():
            bid = data['bid']
            ask = data['ask']
            mid = (bid + ask) / 2
            message += f"• **{exchange.upper()}:** `${mid:.4f}` (Bid: ${bid:.4f} | Ask: ${ask:.4f})\n"

        message += f"\n🕐 *Updated:* `{timestamp}`"
        return message
