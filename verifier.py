# verifier.py — Проверка кодов ТН ВЭД по SQLite, скоринг признаков, получение ставок

import sqlite3
from typing import Optional, Dict, List, Tuple

from config import DB_PATH


def get_db_connection() -> sqlite3.Connection:
    """Создаёт подключение к SQLite с поддержкой словарей."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def verify_code(code: str) -> Optional[Dict]:
    """
    Проверяет наличие кода ТН ВЭД в справочнике и возвращает данные по нему.

    :param code: 10-значный код ТН ВЭД
    :return: словарь с данными кода или None, если не найден
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT code, group_number, description, duty_type, duty_rate, vat_rate, "
            "       excise, keywords, function_features, material_features, "
            "       application_area, updated_at "
            "FROM hs_codes WHERE code = ?",
            (code.strip(),)
        )
        row = cursor.fetchone()
        if row:
            return {
                "code": row["code"],
                "group_number": row["group_number"],
                "description": row["description"],
                "duty_type": row["duty_type"],
                "duty_rate": row["duty_rate"],
                "vat_rate": row["vat_rate"],
                "excise": row["excise"],
                "keywords": row["keywords"],
                "function_features": row["function_features"],
                "material_features": row["material_features"],
                "application_area": row["application_area"],
                "updated_at": row["updated_at"],
                "verified": True,
            }
        return None
    finally:
        conn.close()


def score_code_match(code: str, product_description: str) -> Dict:
    """
    Оценивает степень совпадения описания товара с признаками кода ТН ВЭД.

    Скоринг без ML — простое правило «совпало ключевое слово → +1 балл»:
      - совпало ключевое слово      → +1 за каждое
      - совпало назначение (функция) → +3
      - совпала область применения   → +2
      - совпал материал              → +1

    :param code: код ТН ВЭД
    :param product_description: описание товара
    :return: словарь {score, max_score, details, explanation}
    """
    verified = verify_code(code)
    if not verified:
        return {
            "score": 0,
            "max_score": 0,
            "details": [],
            "explanation": "Код отсутствует в справочнике — скоринг невозможен",
        }

    desc_lower = product_description.lower()
    details = []
    score = 0

    kw_list = [k.strip().lower() for k in verified["keywords"].split(",") if k.strip()]
    matched_kw = [k for k in kw_list if k in desc_lower]
    if matched_kw:
        score += len(matched_kw)
        details.append(f"Ключевые слова ({len(matched_kw)}×1 б.): {', '.join(matched_kw)}")

    func_list = [f.strip().lower() for f in verified["function_features"].split(",") if f.strip()]
    matched_func = [f for f in func_list if f in desc_lower]
    if matched_func:
        score += 3
        details.append(f"Назначение (+3 б.): {', '.join(matched_func)}")

    app_list = [a.strip().lower() for a in verified["application_area"].split(",") if a.strip()]
    matched_app = [a for a in app_list if a in desc_lower]
    if matched_app:
        score += 2
        details.append(f"Область применения (+2 б.): {', '.join(matched_app)}")

    mat_list = [m.strip().lower() for m in verified["material_features"].split(",") if m.strip()]
    matched_mat = [m for m in mat_list if m in desc_lower]
    if matched_mat:
        score += 1
        details.append(f"Материал (+1 б.): {', '.join(matched_mat)}")

    max_score = len(kw_list) + 3 + 2 + 1

    if score == 0:
        explanation = "Совпадений признаков не обнаружено"
    elif score <= 2:
        explanation = f"Низкое совпадение ({score} б.) — рекомендуется дополнительная проверка"
    elif score <= 5:
        explanation = f"Среднее совпадение ({score} б.) — код вероятно подходит"
    else:
        explanation = f"Высокое совпадение ({score} б.) — код соответствует описанию товара"

    return {
        "score": score,
        "max_score": max_score,
        "details": details,
        "explanation": explanation,
    }


def get_duty_info(code: str) -> Optional[Dict]:
    """
    Получает информацию о ставках пошлины и НДС для кода ТН ВЭД.
    """
    verified = verify_code(code)
    if verified:
        return {
            "duty_type": verified["duty_type"],
            "duty_rate": verified["duty_rate"],
            "vat_rate": verified["vat_rate"],
            "excise": verified["excise"],
            "source": "БД (верифицировано)",
        }
    return None


def get_preference_coefficient(country_code: str) -> float:
    """
    Получает коэффициент преференции для страны происхождения.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT coefficient FROM preferences WHERE country_code = ?",
            (country_code.upper(),)
        )
        row = cursor.fetchone()
        return row["coefficient"] if row else 1.0
    finally:
        conn.close()


def get_preference_info(country_code: str) -> Optional[Dict]:
    """
    Получает полную информацию о преференциальном режиме страны.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT country_code, country_name, preference_type, coefficient "
            "FROM preferences WHERE country_code = ?",
            (country_code.upper(),)
        )
        row = cursor.fetchone()
        if row:
            return {
                "country_code": row["country_code"],
                "country_name": row["country_name"],
                "preference_type": row["preference_type"],
                "coefficient": row["coefficient"],
            }
        return None
    finally:
        conn.close()


def get_all_countries() -> List[Tuple[str, str, float]]:
    """
    Возвращает список всех стран из таблицы преференций.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT country_code, country_name, coefficient FROM preferences ORDER BY country_name"
        )
        return [(row["country_code"], row["country_name"], row["coefficient"]) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_customs_fee(customs_value: float) -> float:
    """
    Определяет размер таможенного сбора по шкале (ПП РФ № 1637 в ред. № 1638).
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT fee FROM customs_fees WHERE min_value <= ? AND max_value >= ? "
            "ORDER BY min_value LIMIT 1",
            (customs_value, customs_value)
        )
        row = cursor.fetchone()
        if row:
            return row["fee"]
        return 73860.0
    finally:
        conn.close()


def find_codes_by_description(description: str, top_n: int = 3) -> List[Dict]:
    """
    Ищет коды ТН ВЭД в локальной базе знаний по ключевым словам описания товара.
    Один запрос к БД, дальше — скоринг в памяти.
    Используется как резервный поиск при недоступности LLM или как дополнение к нему.
    """
    desc_lower = description.lower()
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT code, description, duty_type, duty_rate, vat_rate, "
            "keywords, function_features, material_features, application_area "
            "FROM hs_codes"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        score = 0
        details = []

        kw_list = [k.strip().lower() for k in (row["keywords"] or "").split(",") if k.strip()]
        matched_kw = [k for k in kw_list if k in desc_lower]
        if matched_kw:
            score += len(matched_kw)
            details.append(f"Ключевые слова: {', '.join(matched_kw)}")

        func_list = [f.strip().lower() for f in (row["function_features"] or "").split(",") if f.strip()]
        if any(f in desc_lower for f in func_list):
            score += 3
            details.append("Совпало назначение")

        app_list = [a.strip().lower() for a in (row["application_area"] or "").split(",") if a.strip()]
        if any(a in desc_lower for a in app_list):
            score += 2
            details.append("Совпала область применения")

        mat_list = [m.strip().lower() for m in (row["material_features"] or "").split(",") if m.strip()]
        if any(m in desc_lower for m in mat_list):
            score += 1
            details.append("Совпал материал")

        if score > 0:
            results.append({
                "code": row["code"],
                "name": row["description"],
                "reasoning": "Подобрано по локальной базе знаний. " + ", ".join(details) + ".",
                "score": score,
                "source": "db",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def get_knowledge_base_stats() -> Dict:
    """
    Возвращает статистику базы знаний: количество записей в каждой таблице
    и число продукционных правил экспертной подсистемы.
    """
    conn = get_db_connection()
    try:
        hs = conn.execute("SELECT COUNT(*) FROM hs_codes").fetchone()[0]
        pref = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
        fees = conn.execute("SELECT COUNT(*) FROM customs_fees").fetchone()[0]
        return {
            "hs_codes": hs,
            "preferences": pref,
            "customs_fees": fees,
            "rules": 18,
        }
    finally:
        conn.close()


def get_customs_fee_range(customs_value: float) -> Optional[Dict]:
    """
    Возвращает диапазон и сумму таможенного сбора для логирования правил.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT min_value, max_value, fee FROM customs_fees "
            "WHERE min_value <= ? AND max_value >= ? ORDER BY min_value LIMIT 1",
            (customs_value, customs_value)
        )
        row = cursor.fetchone()
        if row:
            return {
                "min_value": row["min_value"],
                "max_value": row["max_value"],
                "fee": row["fee"],
            }
        return None
    finally:
        conn.close()
