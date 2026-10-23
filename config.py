import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
MONGO_URI = os.environ["MONGO_URI"]
DB_NAME = os.getenv("DB_NAME", "contactbot")

# Render gives a dynamic PORT; locally it falls back to 8080
PORT = int(os.getenv("PORT", "8080"))

# Render sets RENDER_EXTERNAL_URL automatically; APP_URL overrides it
APP_URL = os.getenv("APP_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
PING_INTERVAL = int(os.getenv("PING_INTERVAL", "300"))  # seconds (5 minutes)
