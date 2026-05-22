import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("REPORT_CHANNEL_ID", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

_raw_ids = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: set[int] = {int(x) for x in _raw_ids.split(",") if x.strip().isdigit()}

BASE_DIR = Path(__file__).parent

TOUR_DIRECTIONS = [
    "Дагестан",
    "Дагестан 2.0",
    "Абхазия",
    "Грузия",
    "ГрузияЭКС",
    "Карелия",
    "Питер+Карелия",
    "Мурманск",
    "Осетия",
    "Китай",
    "Малайзия",
    "Камчатка",
    "Узбекистан",
]
