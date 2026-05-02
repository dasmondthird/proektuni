# config.py — Конфигурация API YandexGPT
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass  # python-dotenv необязателен; переменные можно задать и напрямую

YANDEX_API_KEY = os.environ.get("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")

YANDEX_API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_MODEL_URI = f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite"

TEMPERATURE = 0.1
MAX_TOKENS = 1024

DB_PATH = os.path.join(BASE_DIR, "db", "customs.db")
