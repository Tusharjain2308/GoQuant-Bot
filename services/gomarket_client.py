import aiohttp
import asyncio
import logging
import httpx
from typing import Optional, Dict, List

class GoMarketClient:
    """Client for interacting with GoMarket APIs"""
    
    def __init__(self):
        self.base_url = "https://gomarket-api.goquant.io/api"
        self.session = None
    
    async def _get_session(self):
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _convert_symbol_format(self, symbol: str, to_api: bool = True) -> str:
        """Convert between user format (BTC-USDT) and API format (BTC_USDT)"""
        if to_api:
            return symbol.replace('-', '_')
        else:
            return symbol.replace('_', '-')
    
    async def get_symbols(self, exchange: str, market_type: str = "spot") -> Optional[List[str]]:
        """
        Get available symbols from an exchange
        
        Args:
            exchange: Exchange name (okx, binance, bybit, deribit)
            market_type: Market type (spot, futures, etc.)
        
        Returns:
            List of symbol strings in user format (BTC-USDT) or None if error
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/symbols/{exchange}/{market_type}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    symbols = []
                    
                    # Extract symbols from different possible response formats
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and 'name' in item:
                                symbol_name = self._convert_symbol_format(item['name'], to_api=False)
                                symbols.append(symbol_name)
                            elif isinstance(item, str):
                                symbols.append(self._convert_symbol_format(item, to_api=False))
                        return symbols
                    elif isinstance(data, dict) and 'symbols' in data:
                        for item in data['symbols']:
                            if isinstance(item, dict) and 'name' in item:
                                symbol_name = self._convert_symbol_format(item['name'], to_api=False)
                                symbols.append(symbol_name)
                        return symbols
                    elif isinstance(data, dict) and 'data' in data:
                        for item in data['data']:
                            if isinstance(item, dict) and 'name' in item:
                                symbol_name = self._convert_symbol_format(item['name'], to_api=False)
                                symbols.append(symbol_name)
                        return symbols
                    else:
                        logging.warning(f"Unexpected response format from {url}: {data}")
                        return []
                else:
                    logging.error(f"Failed to get symbols from {exchange}: HTTP {response.status}")
                    return None
        except Exception as e:
            logging.error(f"Error fetching symbols from {exchange}: {e}")
            return None
    
    async def get_l1_orderbook(self, exchange: str, symbol: str) -> Optional[Dict]:
        """
        Get L1 orderbook data for a symbol
        
        Args:
            exchange: Exchange name
            symbol: Trading symbol (accepts both BTC-USDT and BTC_USDT formats)
        
        Returns:
            Dict with bid/ask data or None if error
        """
        try:
            session = await self._get_session()
            # Convert symbol to API format (underscore)
            api_symbol = self._convert_symbol_format(symbol, to_api=True)
            url = f"{self.base_url}/l1-orderbook/{exchange}/{api_symbol}"
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Normalize the response format
                    if isinstance(data, dict):
                        # Try different possible field names
                        bid = data.get('bid') or data.get('best_bid') or data.get('bidPrice')
                        ask = data.get('ask') or data.get('best_ask') or data.get('askPrice')
                        bid_size = data.get('bid_size') or data.get('bidQty') or data.get('bid_quantity')
                        ask_size = data.get('ask_size') or data.get('askQty') or data.get('ask_quantity')
                        
                        return {
                            'bid': float(bid) if bid else None,
                            'ask': float(ask) if ask else None,
                            'bid_size': float(bid_size) if bid_size else None,
                            'ask_size': float(ask_size) if ask_size else None,
                            'symbol': symbol,
                            'exchange': exchange,
                            'timestamp': data.get('timestamp')
                        }
                    else:
                        logging.warning(f"Unexpected response format from {url}: {data}")
                        return None
                else:
                    logging.error(f"Failed to get orderbook from {exchange} for {symbol}: HTTP {response.status}")
                    return None
        except Exception as e:
            logging.error(f"Error fetching orderbook from {exchange} for {symbol}: {e}")
            return None
    
    async def get_multiple_orderbooks(self, symbols_exchanges: List[tuple]) -> Dict[str, Dict]:
        """
        Get L1 orderbook data for multiple symbol-exchange pairs
        
        Args:
            symbols_exchanges: List of (symbol, exchange) tuples
        
        Returns:
            Dict mapping "{exchange}_{symbol}" to orderbook data
        """
        tasks = []
        for symbol, exchange in symbols_exchanges:
            tasks.append(self.get_l1_orderbook(exchange, symbol))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        orderbooks = {}
        for i, result in enumerate(results):
            symbol, exchange = symbols_exchanges[i]
            key = f"{exchange}_{symbol}"
            
            if isinstance(result, Exception):
                logging.error(f"Error fetching {key}: {result}")
                orderbooks[key] = None
            else:
                orderbooks[key] = result
        
        return orderbooks

    async def get_l2_orderbook(self, exchange: str, symbol: str):
        """
        Fetch L2 order book data for a given exchange and symbol.
        Returns dict with 'bids' and 'asks' as lists of [price, size].
        """
        url = f"{self.base_url}/l2-orderbook/{exchange}/{symbol}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                response.raise_for_status()
                data = response.json()
                if "bids" in data and "asks" in data:
                    # Convert price/size strings to float
                    data["bids"] = [[float(p), float(s)] for p, s in data["bids"]]
                    data["asks"] = [[float(p), float(s)] for p, s in data["asks"]]
                    return data
                else:
                    raise ValueError(f"Invalid L2 format for {exchange} {symbol}")
        except Exception as e:
            logging.error(f"❌ Failed to fetch L2 orderbook for {exchange} {symbol}: {e}")
            return None

    async def is_valid_symbol(self, exchange: str, instrument_type: str, symbol: str) -> bool:
        symbols = await self.get_symbols(exchange, instrument_type)
        return symbol in symbols

    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()

gomarket_client = GoMarketClient()