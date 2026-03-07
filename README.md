# 🛒 Amazon Cart Price Tracker

Standalone Python script that monitors your Amazon.in cart for price drops every 15 minutes and sends alerts to Telegram.

## What It Does

1. **Logs into Amazon** using saved browser cookies
2. **Scans your cart** for price decrease alerts
3. **Compares** dropped prices with your desired prices from `amazon_products.json`
4. **Sends Telegram notifications** — price drops + desired price comparison
5. **Repeats** every 15 minutes (configurable)

## Project Structure

```
price-tracker-updated/
├── main.py               # Entry point (15-min loop)
├── .env                  # Telegram credentials + config
├── requirements.txt
└── app/
    ├── scanner.py        # Playwright scraper + parser + comparator
    ├── notifications.py  # Telegram bot sender
    └── data/
        ├── amazon_cookies.json    # Your Amazon session cookies
        └── amazon_products.json   # Products with desired prices
```

## Local Setup

```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate it
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser
playwright install chromium

# 5. Configure environment
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID

# 6. Add your data files
# Place amazon_cookies.json and amazon_products.json in app/data/

tmux attach -t pricebot

# 7. Run
python main.py
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from @BotFather | — |
| `TELEGRAM_CHAT_ID` | Your Telegram chat/user ID | — |
| `SCAN_INTERVAL_MINUTES` | Interval between scans | `15` |

## Data Files

### `amazon_cookies.json`

Export your Amazon.in cookies using a browser extension (e.g., "EditThisCookie") and save as JSON array.

### `amazon_products.json`

```json
[
  {
    "name": "Product Name",
    "desired_price": 199,
    "mrp": 350
  }
]
```

## ☁️ Cloud Deployment

### Option 1: Railway / Render (Recommended)

1. Push to GitHub (cookies & `.env` are gitignored)
2. Connect repo to [Railway](https://railway.app) or [Render](https://render.com)
3. Set environment variables in the dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `SCAN_INTERVAL_MINUTES`
4. **Build command:**
   ```bash
   pip install -r requirements.txt && playwright install chromium && playwright install-deps
   ```
5. **Start command:**
   ```bash
   python main.py
   ```
6. Upload `amazon_cookies.json` and `amazon_products.json` to the `app/data/` directory (or use environment variables / mounted volumes)

### Option 2: VPS (DigitalOcean, AWS EC2, etc.)

```bash
# SSH into your server
git clone <your-repo-url>
cd price-tracker-updated

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps  # installs system dependencies

# Set up .env
nano .env

# Add data files
nano app/data/amazon_cookies.json
nano app/data/amazon_products.json

# Run with nohup (persists after SSH disconnect)
nohup python main.py > scanner.log 2>&1 &

# Or use screen/tmux
screen -S tracker
python main.py
# Ctrl+A, D to detach
```

### Option 3: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install chromium && playwright install-deps
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t price-tracker .
docker run -d --env-file .env -v ./app/data:/app/app/data price-tracker
```

> **Note:** For cloud deployments, ensure `amazon_cookies.json` is uploaded securely and refreshed periodically as Amazon cookies expire.
