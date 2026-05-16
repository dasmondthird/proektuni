# config.py — Конфигурация API YandexGPT и путей к базам данных
import os
import sys

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

# ── Пути к профессиональным справочникам ──
# Google Drive file ID для автоскачивания на Streamlit Cloud
GDRIVE_REF_DB_ID = "1VZDNn81GS1SKDf-voph0hKfp6U4I6O3n"

# Порядок поиска баз данных:
#   1) Переменная окружения CUSTOMS_DATA_DIR (если задана)
#   2) Локальный путь ~/Desktop/apsps/CustomsData (для рабочего стола)
#   3) /tmp/customs_data (для Streamlit Cloud — автоскачивание с Google Drive)
_LOCAL_DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "apsps", "CustomsData")
_CLOUD_DATA_DIR = os.path.join("/tmp", "customs_data")

CUSTOMS_DATA_DIR = os.environ.get("CUSTOMS_DATA_DIR", "")

if not CUSTOMS_DATA_DIR:
    # Проверяем локальный путь
    if os.path.exists(os.path.join(_LOCAL_DATA_DIR, "CustomsReference.DB")):
        CUSTOMS_DATA_DIR = _LOCAL_DATA_DIR
    else:
        # Облачный режим — скачаем в /tmp
        CUSTOMS_DATA_DIR = _CLOUD_DATA_DIR


def _download_from_gdrive(file_id: str, dest_path: str) -> bool:
    """Скачивание файла с Google Drive через gdown (обходит подтверждение для больших файлов)."""
    try:
        import gdown
    except ImportError:
        print("[config] gdown не установлен, автоскачивание невозможно", file=sys.stderr)
        return False

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    url = f"https://drive.google.com/uc?id={file_id}"
    try:
        print(f"[config] Скачивание базы данных с Google Drive → {dest_path}")
        gdown.download(url, dest_path, quiet=False)
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1_000_000
    except Exception as e:
        print(f"[config] Ошибка скачивания: {e}", file=sys.stderr)
        return False


CUSTOMS_REF_DB = os.path.join(CUSTOMS_DATA_DIR, "CustomsReference.DB")
USER_DATA_DB = os.path.join(CUSTOMS_DATA_DIR, "UserData.DB")

# Автоскачивание CustomsReference.DB если не найден
if not os.path.exists(CUSTOMS_REF_DB) and GDRIVE_REF_DB_ID:
    _download_from_gdrive(GDRIVE_REF_DB_ID, CUSTOMS_REF_DB)

REF_DB_AVAILABLE = os.path.exists(CUSTOMS_REF_DB)
USER_DB_AVAILABLE = os.path.exists(USER_DATA_DB)
