# 🤖 GoQuant Arbitrage Signal Bot

A real-time, multi-exchange arbitrage signal detector built using Python, Telegram Bot API, and GoMarket API. This bot fetches market data, detects profitable arbitrage opportunities, and pushes live alerts with professional UX directly to Telegram.

---

## 🧱 System Architecture

 
![Folder Structure](./assets/folder.png)

![System Architecture](./assets/architecture.png)

---

## 🔁 GoMarket Data Flow

- **Symbols:** Pulled dynamically from `/api/symbols/{exchange}/{market_type}`
- I have worked with SPOT as the instrument_type throughtout the assignment.
- **Orderbook:** Fetched via `/api/orderbook/{exchange}/{symbol}/{level}`
- **Usage:**
  - Symbols are parsed and normalized (BTC/USDT → BTC-USDT)
  - L1/L2 orderbooks are used to compute arbitrage and CBBO signals

Data is fetched dynamically, parsed, and normalized across all supported exchanges.

---

## ✅ Arbitrage Strategy

The bot continuously scans real-time market data from multiple exchanges to find profitable arbitrage opportunities.

### 📌 Strategy Overview:

- **Buy** at the exchange offering the **lowest ask price**
- **Sell** at the exchange offering the **highest bid price**
- **Spread** is calculated as:  
  `Spread = Highest Bid - Lowest Ask`
- If the **Spread %** crosses a user-defined threshold, the bot sends a **signal**.

---

## 🔍 Arbitrage Detection Logic

1. **L1 Data Collection**  
   Real-time Level 1 (L1) order book data is fetched across exchanges for the selected trading pair using the GoMarket API.

2. **Best Price Discovery**  
   - Identify the exchange offering the **highest bid**
   - Identify the exchange offering the **lowest ask**

3. **Spread Calculation**  
   The spread percentage is computed using the formula:  
`Spread % = ((Best Bid - Best Ask) / Best Ask) * 100`


4. **Signal Triggering**  
If the computed spread meets or exceeds the user-defined threshold, an arbitrage opportunity is signaled.

---

## 🏆 Arbitrage Signal Output

When a signal is triggered, the bot sends a cleanly formatted message including:

- 🟢 **Buy Exchange**: Where to buy (lowest ask)
- 🔴 **Sell Exchange**: Where to sell (highest bid)
- 📊 **Spread Percentage**: Profit potential in %
- 📈 **Mid Price**: Average of the best bid and best ask
- 🏦 **Per-Exchange BBO** (Best Bid/Offer):  
Displays the top bid and ask prices from each exchange for full transparency

The message is formatted using **Markdown** and emojis for better readability within the Telegram bot interface.

---

## 📊 CBBO (Consolidated Best Bid/Offer) View

The CBBO feature provides a real-time snapshot of the market by aggregating top bids and asks across all supported exchanges.

### What It Shows:

- 🟦 **Best Bid**: The highest bid price across all exchanges
- 🟥 **Best Ask**: The lowest ask price across all exchanges
- 📈 **Mid Price**: `(Best Bid + Best Ask) / 2`


### Also Includes:

- 🏅 **Best Bid Venue**: Exchange with the best bid
- 🥇 **Best Ask Venue**: Exchange with the best ask
- 💱 **Per-Exchange BBO**:  
A breakdown of the top bid and ask on each exchange

All this information is sent to the user via a **Telegram message**, styled for quick visual understanding.

---


## 🤖 Telegram Bot UX & Commands

### 🧭 Main Menu Options:
- 📋 View Exchanges & Symbols
- 🔍 Check Arbitrage
- 📡 Monitor Arbitrage
- 💱 View Live Price (L1 Orderbook)
- ⛔ Stop / Reset

### 🔐 Command Descriptions:
- `/get_cbbo <symbol> [exchange1 exchange2 ...]`: Show CBBO and mid-price across venues
- `/monitor_arb <symbol> <threshold>`: Start live arbitrage alerts
- `/stop`: Stop all services
- `/reset`: Reset all data (DB + runtime)

### 🎯 UX Flow:
/start or menu tap
→ Choose exchange
→ Choose symbol
→ Choose threshold
→ Live arbitrage monitoring starts

yaml
Copy
Edit

- Inline buttons
- Markdown formatting
- Emojis to enhance readability

---

## 🧠 Assumptions Made about GoMarket APIs

- `/symbols/{exchange}/{market_type}` may return:
  - List of strings
  - List of objects with `name` key
  - Dict with `symbols` or `data` keys
- `/orderbook/...` returns `bids` and `asks` as lists of [price, qty]
- All symbol formats are normalized using a utility
- Exchanges supported: `okx`, `binance`, `bybit`, `deribit`
- Network failures or 500 responses are caught and logged

---

## ⚙️ Setup & Deployment

### ✅ Requirements:
- Python 3.8+
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Access to GoMarket backend (real or simulated)

---

### 🛠️ Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/GoQuant.git
cd GoQuant

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

Setup the .env file as follows - 
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

Running the Bot
bash
Copy
Edit
# Entry point
python -m main
Use /start in your Telegram bot to interact

Set up dynamic thresholds for alerts

View L1 orderbooks or CBBO as needed

👨‍💻 Author
Tushar Jain
📧 tusharjain2308@gmail.com
🌐 Portfolio
🐙 GitHub
💼 LinkedIn
