# config.py — Конфигурация API YandexGPT и путей к базам данных
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Локально читаем .env, если он есть
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

# В Streamlit Cloud секреты лежат в st.secrets,
# локально можно использовать переменные окружения или .env
try:
    import streamlit as st
except Exception:
    st = None


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value

    if st is not None:
        try:
            return st.secrets.get(name, default)
        except Exception:
            return default

    return default


YANDEX_API_KEY = get_secret("YANDEX_API_KEY")
YANDEX_FOLDER_ID = get_secret("YANDEX_FOLDER_ID")

YANDEX_API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YANDEX_MODEL_URI = f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite"

TEMPERATURE = 0.1
MAX_TOKENS = 1024

DB_PATH = os.path.join(BASE_DIR, "db", "customs.db")

CUSTOMS_DATA_DIR = os.environ.get(
    "CUSTOMS_DATA_DIR",
    os.path.join(os.path.expanduser("~"), "Desktop", "apsps", "CustomsData"),
)
CUSTOMS_REF_DB = os.path.join(CUSTOMS_DATA_DIR, "CustomsReference.DB")
USER_DATA_DB = os.path.join(CUSTOMS_DATA_DIR, "UserData.DB")

REF_DB_AVAILABLE = os.path.exists(CUSTOMS_REF_DB)
USER_DB_AVAILABLE = os.path.exists(USER_DATA_DB)
