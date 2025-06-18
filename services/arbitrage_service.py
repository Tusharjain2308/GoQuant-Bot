import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List

from sqlalchemy.orm import Session
from models import MonitoredSymbol, ArbitrageAlert, TelegramChat
from services.gomarket_client import GoMarketClient
from db.session import SessionLocal 

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    Bot = None
    ParseMode = None
    TELEGRAM_AVAILABLE = False

class ArbitrageService:
    """Service for detecting and alerting on arbitrage opportunities"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.gomarket_client = GoMarketClient()
        self.is_running = False
        self.check_interval = 10  # seconds

    async def start(self):
        """Start the arbitrage monitoring service"""
        self.is_running = True
        logging.info("Arbitrage service started")

        while self.is_running:
            try:
                await self.check_arbitrage_opportunities()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logging.error(f"Error in arbitrage service: {e}")
                await asyncio.sleep(self.check_interval)

    def stop(self):
        """Stop the arbitrage monitoring service"""
        self.is_running = False
        logging.info("Arbitrage service stopped")

    async def check_arbitrage_opportunities(self):
        """Check for arbitrage opportunities and send alerts"""
        session: Session = SessionLocal()
        try:
            monitored_symbols = session.query(MonitoredSymbol).filter_by(is_active=True).all()
            if not monitored_symbols:
                return

            symbols_dict = {}
            for ms in monitored_symbols:
                if ms.symbol not in symbols_dict:
                    symbols_dict[ms.symbol] = []
                symbols_dict[ms.symbol].append(ms)

            for symbol, monitors in symbols_dict.items():
                if len(monitors) < 2:
                    continue
                await self._check_symbol_arbitrage(symbol, monitors)
        finally:
            session.close()

    async def _check_symbol_arbitrage(self, symbol: str, monitors: List[MonitoredSymbol]):
        """Check arbitrage opportunities for a specific symbol"""
        try:
            exchange_data = {}
            for monitor in monitors:
                data = await self.gomarket_client.get_l1_orderbook(monitor.exchange, symbol)
                if data and data.get('bid') and data.get('ask'):
                    exchange_data[monitor.exchange] = {
                        'data': data,
                        'monitor': monitor
                    }

            if len(exchange_data) < 2:
                return

            exchanges = list(exchange_data.keys())
            for i in range(len(exchanges)):
                for j in range(i + 1, len(exchanges)):
                    ex1, ex2 = exchanges[i], exchanges[j]
                    await self._check_pair_arbitrage(symbol, exchange_data[ex1], exchange_data[ex2])

        except Exception as e:
            logging.error(f"Error checking arbitrage for {symbol}: {e}")

    async def _check_pair_arbitrage(self, symbol: str, ex1_data: Dict, ex2_data: Dict):
        """Check arbitrage between two exchanges"""
        try:
            ex1_name = ex1_data['data']['exchange']
            ex2_name = ex2_data['data']['exchange']

            ex1_bid = ex1_data['data']['bid']
            ex1_ask = ex1_data['data']['ask']
            ex2_bid = ex2_data['data']['bid']
            ex2_ask = ex2_data['data']['ask']

            spread1 = ex2_bid - ex1_ask
            spread1_pct = (spread1 / ex1_ask) * 100 if ex1_ask > 0 else 0
            spread2 = ex1_bid - ex2_ask
            spread2_pct = (spread2 / ex2_ask) * 100 if ex2_ask > 0 else 0

            threshold_pct = min(ex1_data['monitor'].threshold_percentage, ex2_data['monitor'].threshold_percentage)
            threshold_amt = min(ex1_data['monitor'].threshold_amount, ex2_data['monitor'].threshold_amount)

            opportunity = None
            if spread1 > 0 and (spread1_pct >= threshold_pct or spread1 >= threshold_amt):
                opportunity = {
                    'buy_exchange': ex1_name,
                    'sell_exchange': ex2_name,
                    'buy_price': ex1_ask,
                    'sell_price': ex2_bid,
                    'spread': spread1,
                    'spread_pct': spread1_pct
                }
            elif spread2 > 0 and (spread2_pct >= threshold_pct or spread2 >= threshold_amt):
                opportunity = {
                    'buy_exchange': ex2_name,
                    'sell_exchange': ex1_name,
                    'buy_price': ex2_ask,
                    'sell_price': ex1_bid,
                    'spread': spread2,
                    'spread_pct': spread2_pct
                }

            if opportunity:
                await self._handle_arbitrage_opportunity(symbol, opportunity)

        except Exception as e:
            logging.error(f"Error checking pair arbitrage: {e}")

    async def _handle_arbitrage_opportunity(self, symbol: str, opportunity: Dict):
        """Handle detected arbitrage opportunity"""
        session: Session = SessionLocal()
        try:
            recent_cutoff = datetime.utcnow() - timedelta(minutes=5)
            recent_alert = session.query(ArbitrageAlert).filter(
                ArbitrageAlert.asset1 == symbol,
                ArbitrageAlert.exchange1 == opportunity['buy_exchange'],
                ArbitrageAlert.exchange2 == opportunity['sell_exchange'],
                ArbitrageAlert.timestamp > recent_cutoff,
                ArbitrageAlert.is_active == True
            ).first()

            if recent_alert:
                return

            alert = ArbitrageAlert(
                asset1=symbol,
                asset2=symbol,
                exchange1=opportunity['buy_exchange'],
                exchange2=opportunity['sell_exchange'],
                price1=opportunity['buy_price'],
                price2=opportunity['sell_price'],
                spread_percentage=opportunity['spread_pct'],
                spread_amount=opportunity['spread']
            )
            session.add(alert)
            session.commit()

            active_chats = session.query(TelegramChat).filter_by(
                is_active=True,
                arbitrage_enabled=True
            ).all()

            message = self._format_arbitrage_alert(symbol, opportunity)

            for chat in active_chats:
                try:
                    await self.bot.send_message(
                        chat_id=chat.chat_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logging.error(f"Failed to send alert to chat {chat.chat_id}: {e}")
        except Exception as e:
            logging.error(f"Error handling arbitrage opportunity: {e}")
        finally:
            session.close()

    def _format_arbitrage_alert(self, symbol: str, opportunity: Dict) -> str:
        """Format arbitrage opportunity as Telegram message"""
        timestamp = datetime.now().strftime('%H:%M:%S UTC')

        message = f"🚨 *ARBITRAGE OPPORTUNITY DETECTED* 🚨\n\n"
        message += f"💰 *Symbol:* `{symbol}`\n"
        message += f"📈 *Spread:* `{opportunity['spread_pct']:.2f}%` (${opportunity['spread']:.2f})\n\n"
        message += f"🔻 *BUY* on **{opportunity['buy_exchange'].upper()}**\n"
        message += f"   Price: `${opportunity['buy_price']:.4f}`\n\n"
        message += f"🔺 *SELL* on **{opportunity['sell_exchange'].upper()}**\n"
        message += f"   Price: `${opportunity['sell_price']:.4f}`\n\n"
        message += f"🕐 *Time:* `{timestamp}`\n"
        message += f"⚡ *Action Required:* Execute trades quickly!"

        return message
