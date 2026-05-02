# classifier.py — Модуль запросов к YandexGPT API для классификации товаров

import json
import requests
from typing import List, Dict

from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_API_URL, YANDEX_MODEL_URI, TEMPERATURE, MAX_TOKENS
from prompts import SYSTEM_PROMPT, build_user_prompt


def classify_product(description: str) -> List[Dict[str, str]]:
    """
    Отправляет описание товара в YandexGPT и получает 3 рекомендуемых кода ТН ВЭД.

    :param description: текстовое описание товара
    :return: список из 3 словарей {code, name, reasoning}
    :raises ConnectionError: при проблемах с сетью или отсутствии API-ключа
    :raises ValueError: при невалидном ответе от API
    """
    description = description.strip()
    if not description:
        raise ValueError("Описание товара не может быть пустым.")

    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise ConnectionError(
            "API-ключ или Folder ID YandexGPT не настроены. "
            "Задайте переменные окружения YANDEX_API_KEY и YANDEX_FOLDER_ID "
            "в файле .env или в настройках системы."
        )

    payload = {
        "modelUri": YANDEX_MODEL_URI,
        "completionOptions": {
            "stream": False,
            "temperature": TEMPERATURE,
            "maxTokens": str(MAX_TOKENS),
        },
        "messages": [
            {"role": "system", "text": SYSTEM_PROMPT},
            {"role": "user", "text": build_user_prompt(description)},
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
    }

    try:
        session = requests.Session()
        session.trust_env = False
        response = session.post(YANDEX_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            "Нет подключения к интернету. Проверьте сетевое соединение."
        )
    except requests.exceptions.Timeout:
        raise ConnectionError(
            "Превышено время ожидания ответа от YandexGPT (30 сек). Попробуйте позже."
        )
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "неизвестен"
        raise ConnectionError(
            f"Ошибка HTTP {status} при запросе к YandexGPT API. Проверьте API-ключ и Folder ID."
        )

    return _parse_response(response.json())


def _parse_response(api_response: dict) -> List[Dict[str, str]]:
    try:
        result_text = api_response["result"]["alternatives"][0]["message"]["text"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(
            "Неожиданная структура ответа от YandexGPT API. "
            "Возможно, изменился формат API."
        )

    result_text = result_text.strip()
    if result_text.startswith("```"):
        lines = [l for l in result_text.split("\n") if not l.strip().startswith("```")]
        result_text = "\n".join(lines)

    try:
        codes = json.loads(result_text)
    except json.JSONDecodeError:
        start = result_text.find("[")
        end = result_text.rfind("]")
        if start != -1 and end != -1:
            try:
                codes = json.loads(result_text[start:end + 1])
            except json.JSONDecodeError:
                raise ValueError(
                    f"YandexGPT вернул невалидный JSON. Попробуйте переформулировать запрос.\n"
                    f"Ответ модели: {result_text[:500]}"
                )
        else:
            raise ValueError(
                f"YandexGPT не вернул JSON-массив. Попробуйте переформулировать запрос.\n"
                f"Ответ модели: {result_text[:500]}"
            )

    if not isinstance(codes, list):
        raise ValueError("Ответ модели не является массивом.")

    validated = []
    for item in codes[:3]:
        if not isinstance(item, dict):
            continue
        validated.append({
            "code": str(item.get("code", "")).strip(),
            "name": str(item.get("name", "Описание не предоставлено")).strip(),
            "reasoning": str(item.get("reasoning", "Обоснование не предоставлено")).strip(),
        })

    if not validated:
        raise ValueError("YandexGPT не вернул ни одного кода ТН ВЭД.")

    return validated
