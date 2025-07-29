import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
import logging

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("Ошибка: в файле .env не найден BOT_TOKEN")
    sys.exit(1)

ADMIN_IDS = set()
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = set(map(int, filter(None, os.getenv("ADMIN_IDS").split(","))))

DATABASE_URL = os.getenv("DATABASE_URL_PROD")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

scheduler = BackgroundScheduler()
scheduler.start()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)