# verifier.py — Проверка кодов ТН ВЭД по профессиональному справочнику CustomsReference.DB
#
# Работает с двумя внешними БД (466 МБ + 18 МБ) и локальной БД для таможенных сборов.

import sqlite3
import re
from typing import Optional, Dict, List, Tuple
from datetime import date

from config import DB_PATH, CUSTOMS_REF_DB, USER_DATA_DB, REF_DB_AVAILABLE, USER_DB_AVAILABLE


_EAEU_MEMBERS = {"KZ", "BY", "AM", "KG"}

_DEVELOPING_COUNTRIES = {
    "IN", "VN", "RS", "EG", "BD", "ET", "TZ", "KE", "GH", "SN",
    "MZ", "KH", "MM", "LA", "NP", "LK", "PK", "ID", "PH", "TH",
    "MY", "BR", "AR", "CL", "CO", "PE", "EC", "UY", "PY", "MX",
    "CR", "PA", "DO", "CU", "JM", "NG", "CM", "CI", "DZ", "MA",
    "TN", "JO", "LB", "IR", "IQ", "SY",
}

_LEAST_DEVELOPED = {
    "BD", "ET", "TZ", "MZ", "SN", "KH", "MM", "LA", "NP",
    "AF", "BF", "BI", "TD", "CD", "ER", "GN", "GW", "HT",
    "KI", "LS", "LR", "MG", "MW", "ML", "MR", "NE", "RW",
    "ST", "SL", "SO", "SS", "SD", "TL", "TG", "TV", "UG",
    "VU", "YE", "ZM",
}


def _smart_text(data):
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("cp1251", errors="replace")
    return str(data) if data is not None else ""


def _ref_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(CUSTOMS_REF_DB)
    conn.text_factory = _smart_text
    conn.row_factory = sqlite3.Row
    return conn


def _user_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(USER_DATA_DB)
    conn.text_factory = _smart_text
    conn.row_factory = sqlite3.Row
    return conn


def _local_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _today() -> str:
    return date.today().isoformat()


# ═══════════════════════════════════════════════════════════════
# 1. Верификация кода ТН ВЭД (TNVEDHead)
# ═══════════════════════════════════════════════════════════════

def verify_code(code: str) -> Optional[Dict]:
    code = code.strip()
    if not code or not REF_DB_AVAILABLE:
        return None

    conn = _ref_conn()
    try:
        cursor = conn.execute(
            "SELECT _id, Code, AddCode, Name, LongName, MeasureUnitQualifierCode "
            "FROM TNVEDHead WHERE Code = ? LIMIT 1",
            (code,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        duty = _get_base_duty(conn, code)
        vat = _get_vat_rate(conn, code)
        excise = _get_excise_rate(conn, code)

        duty_type = "адвалорная"
        duty_rate = 0.0
        if duty:
            duty_rate = duty["rate"] or 0.0
            sign = duty["rate_sign"]
            if sign == "%":
                duty_type = "адвалорная"
            elif sign in ("978", "840"):
                duty_type = "специфическая"
            if duty.get("alt_rate") is not None:
                duty_type = "комбинированная"

        try:
            group_number = int(code[:2])
        except ValueError:
            group_number = 0

        description = row["Name"] or row["LongName"] or ""

        return {
            "code": code,
            "group_number": group_number,
            "description": description,
            "long_description": row["LongName"] or description,
            "duty_type": duty_type,
            "duty_rate": duty_rate,
            "vat_rate": vat if vat is not None else 22.0,
            "excise": excise or 0,
            "measure_unit": row["MeasureUnitQualifierCode"] or "",
            "keywords": "",
            "function_features": "",
            "material_features": "",
            "application_area": "",
            "updated_at": _today(),
            "verified": True,
            "source": "CustomsReference.DB",
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 2. Ставки ввозной пошлины (EntranceDuty)
# ═══════════════════════════════════════════════════════════════

def _get_base_duty(conn, code: str, ref_date: str = None) -> Optional[Dict]:
    if ref_date is None:
        ref_date = _today()
    cursor = conn.execute(
        "SELECT Rate, RateSign, MeasureUnitCode, "
        "       AddRate, AddRateSign, AddMeasureUnitCode, "
        "       AltRate, AltRateSign, AltMeasureUnitCode "
        "FROM EntranceDuty "
        "WHERE BeginCode <= ? AND EndCode >= ? "
        "  AND Rate IS NOT NULL "
        "  AND (ApplyCountries IS NULL OR ApplyCountries = '') "
        "  AND (Preference IS NULL OR Preference = '') "
        "  AND BeginDate <= ? "
        "  AND (EndDate IS NULL OR EndDate = '' OR EndDate >= ?) "
        "ORDER BY BeginDate DESC LIMIT 1",
        (code, code, ref_date, ref_date),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "rate": row["Rate"],
        "rate_sign": row["RateSign"],
        "rate_unit": row["MeasureUnitCode"],
        "add_rate": row["AddRate"],
        "add_rate_sign": row["AddRateSign"],
        "add_rate_unit": row["AddMeasureUnitCode"],
        "alt_rate": row["AltRate"],
        "alt_rate_sign": row["AltRateSign"],
        "alt_rate_unit": row["AltMeasureUnitCode"],
    }


def get_duty_info(code: str) -> Optional[Dict]:
    if not REF_DB_AVAILABLE:
        return None

    conn = _ref_conn()
    try:
        duty = _get_base_duty(conn, code)
        vat = _get_vat_rate(conn, code)
        excise = _get_excise_rate(conn, code)

        if duty is None:
            return None

        rate = duty["rate"] or 0.0
        sign = duty["rate_sign"]

        if sign == "%":
            duty_type = "адвалорная"
        elif sign in ("978", "840"):
            duty_type = "специфическая"
        else:
            duty_type = "адвалорная"

        if duty.get("alt_rate") is not None:
            duty_type = "комбинированная"

        return {
            "duty_type": duty_type,
            "duty_rate": rate,
            "rate_sign": sign,
            "rate_unit": duty["rate_unit"],
            "add_rate": duty["add_rate"],
            "add_rate_sign": duty["add_rate_sign"],
            "add_rate_unit": duty["add_rate_unit"],
            "alt_rate": duty["alt_rate"],
            "alt_rate_sign": duty["alt_rate_sign"],
            "alt_rate_unit": duty["alt_rate_unit"],
            "vat_rate": vat if vat is not None else 22.0,
            "excise": excise or 0,
            "source": "CustomsReference.DB (верифицировано)",
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 3. НДС (VAT)
# ═══════════════════════════════════════════════════════════════

def _get_vat_rate(conn, code: str, ref_date: str = None) -> Optional[float]:
    if ref_date is None:
        ref_date = _today()
    cursor = conn.execute(
        "SELECT Rate FROM VAT "
        "WHERE BeginCode <= ? AND EndCode >= ? "
        "  AND Rate IS NOT NULL "
        "  AND (Preference IS NULL OR Preference = '') "
        "  AND BeginDate <= ? "
        "  AND (EndDate IS NULL OR EndDate = '' OR EndDate >= ?) "
        "ORDER BY BeginDate DESC LIMIT 1",
        (code, code, ref_date, ref_date),
    )
    row = cursor.fetchone()
    return row["Rate"] if row else None


# ═══════════════════════════════════════════════════════════════
# 4. Акцизы (Excise)
# ═══════════════════════════════════════════════════════════════

def _get_excise_rate(conn, code: str, ref_date: str = None) -> Optional[float]:
    if ref_date is None:
        ref_date = _today()
    cursor = conn.execute(
        "SELECT Rate, RateSign, MeasureUnitCode FROM Excise "
        "WHERE BeginCode <= ? AND EndCode >= ? "
        "  AND Rate IS NOT NULL "
        "  AND BeginDate <= ? "
        "  AND (EndDate IS NULL OR EndDate = '' OR EndDate >= ?) "
        "ORDER BY BeginDate DESC LIMIT 1",
        (code, code, ref_date, ref_date),
    )
    row = cursor.fetchone()
    return row["Rate"] if row else None


# ═══════════════════════════════════════════════════════════════
# 5. Страны (WorldCountries) и преференции
# ═══════════════════════════════════════════════════════════════

def get_country_info(alpha_code: str) -> Optional[Dict]:
    if not REF_DB_AVAILABLE:
        return None
    conn = _ref_conn()
    try:
        cursor = conn.execute(
            "SELECT _id, Code, AlphaCode, AlphaCode3, ShortName, Name, "
            "       DutySign, Unfriendly "
            "FROM WorldCountries "
            "WHERE (AlphaCode = ? OR AlphaCode3 = ?) "
            "  AND (EndDate IS NULL OR EndDate = '' OR EndDate >= ?) "
            "ORDER BY BeginDate DESC LIMIT 1",
            (alpha_code.upper(), alpha_code.upper(), _today()),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "code": row["Code"],
            "alpha2": row["AlphaCode"],
            "alpha3": row["AlphaCode3"],
            "short_name": row["ShortName"],
            "full_name": row["Name"],
            "duty_sign": row["DutySign"],
            "unfriendly": row["Unfriendly"],
        }
    finally:
        conn.close()


def get_all_countries() -> List[Tuple[str, str, float]]:
    if not REF_DB_AVAILABLE:
        return []
    conn = _ref_conn()
    try:
        cursor = conn.execute(
            "SELECT AlphaCode, ShortName FROM WorldCountries "
            "WHERE AlphaCode IS NOT NULL AND AlphaCode != '' "
            "  AND (EndDate IS NULL OR EndDate = '' OR EndDate >= ?) "
            "GROUP BY AlphaCode "
            "ORDER BY ShortName",
            (_today(),),
        )
        result = []
        seen = set()
        for row in cursor.fetchall():
            ac = row["AlphaCode"]
            if ac in seen:
                continue
            seen.add(ac)
            coeff = _preference_coefficient_for(ac)
            result.append((ac, row["ShortName"], coeff))
        return result
    finally:
        conn.close()


def _preference_coefficient_for(alpha2: str) -> float:
    alpha2 = alpha2.upper()
    if alpha2 in _EAEU_MEMBERS:
        return 0.0
    if alpha2 in _LEAST_DEVELOPED:
        return 0.0
    if alpha2 in _DEVELOPING_COUNTRIES:
        return 0.75
    return 1.0


def _preference_type_for(alpha2: str) -> str:
    alpha2 = alpha2.upper()
    if alpha2 in _EAEU_MEMBERS:
        return "нулевая ставка (ЕАЭС)"
    if alpha2 in _LEAST_DEVELOPED:
        return "нулевая ставка (наименее развитая)"
    if alpha2 in _DEVELOPING_COUNTRIES:
        return "преференциальная (развивающаяся)"
    return "базовая"


def get_preference_coefficient(country_code: str) -> float:
    return _preference_coefficient_for(country_code)


def get_preference_info(country_code: str) -> Optional[Dict]:
    cc = country_code.upper()
    info = get_country_info(cc)
    name = info["short_name"] if info else cc
    return {
        "country_code": cc,
        "country_name": name,
        "preference_type": _preference_type_for(cc),
        "coefficient": _preference_coefficient_for(cc),
    }


# ═══════════════════════════════════════════════════════════════
# 6. Курсы валют (UserData.DB → CurrencyRates)
# ═══════════════════════════════════════════════════════════════

def get_currency_rate(alpha_code: str, ref_date: str = None) -> Optional[Dict]:
    if not USER_DB_AVAILABLE:
        return None
    if ref_date is None:
        ref_date = _today()
    conn = _user_conn()
    try:
        cursor = conn.execute(
            "SELECT Rate, Amount, BeginDate FROM CurrencyRates "
            "WHERE AlphaCode = ? AND BeginDate <= ? "
            "ORDER BY BeginDate DESC LIMIT 1",
            (alpha_code.upper(), ref_date),
        )
        row = cursor.fetchone()
        if not row:
            return None
        amount = row["Amount"] or 1
        return {
            "rate": row["Rate"] / amount if amount != 1 else row["Rate"],
            "raw_rate": row["Rate"],
            "amount": amount,
            "date": row["BeginDate"],
            "alpha_code": alpha_code.upper(),
        }
    finally:
        conn.close()


def get_latest_rates() -> Dict[str, float]:
    result = {}
    for code in ("USD", "EUR", "CNY", "GBP", "JPY", "KRW", "TRY"):
        info = get_currency_rate(code)
        if info:
            result[code] = round(info["rate"], 4)
    return result


# ═══════════════════════════════════════════════════════════════
# 7. Обновление курсов ЦБ РФ
# ═══════════════════════════════════════════════════════════════

def update_currency_rates_from_cbr(target_date: date = None) -> bool:
    if not USER_DB_AVAILABLE:
        return False
    import requests
    from xml.etree import ElementTree

    if target_date is None:
        target_date = date.today()
    url = f"https://www.cbr.ru/scripts/XML_daily.asp?date_req={target_date:%d/%m/%Y}"

    try:
        resp = requests.get(url, timeout=15)
        resp.encoding = "windows-1251"
        root = ElementTree.fromstring(resp.text.encode("utf-8"))
    except Exception:
        return False

    conn = sqlite3.connect(USER_DATA_DB)
    try:
        cursor = conn.cursor()
        date_str = target_date.isoformat()
        inserted = 0
        for valute in root.findall("Valute"):
            num_code = valute.findtext("NumCode", "").strip()
            char_code = valute.findtext("CharCode", "").strip()
            nominal = int(valute.findtext("Nominal", "1").strip())
            value_str = valute.findtext("Value", "0").strip().replace(",", ".")
            rate = float(value_str)

            existing = cursor.execute(
                "SELECT _id FROM CurrencyRates WHERE AlphaCode = ? AND BeginDate = ?",
                (char_code, date_str),
            ).fetchone()
            if existing:
                continue

            cursor.execute(
                "INSERT INTO CurrencyRates (Code, AlphaCode, Amount, Rate, BeginDate) "
                "VALUES (?, ?, ?, ?, ?)",
                (num_code, char_code, nominal, rate, date_str),
            )
            inserted += 1
        conn.commit()
        return inserted > 0
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 8. Поиск кодов по описанию (AlphabeticalIndex + TNVEDHead)
# ═══════════════════════════════════════════════════════════════

_STOP_WORDS = {
    # Предлоги, союзы, частицы, местоимения (бесполезны для поиска товара)
    "для", "или", "при", "что", "как", "это", "его", "они", "все", "них",
    "она", "оно", "они", "наш", "ваш", "так", "уже", "еще", "ещё", "тот",
    "эта", "эти", "кто", "где", "чем", "чей", "нас", "вас", "без", "под",
    "над", "про", "через", "между", "после", "перед", "около", "кроме",
    "the", "and", "for", "with", "from", "this", "that", "not", "are",
    "прочие", "части", "другие", "другое", "прочее", "том", "числе",
    "включая", "также", "более", "менее", "ином", "месте",
}


def find_codes_by_description(description: str, top_n: int = 5) -> List[Dict]:
    if not REF_DB_AVAILABLE:
        return []

    desc_lower = description.lower().strip()
    if not desc_lower:
        return []

    # Извлечение значимых слов (мин. 3 буквы), убираем стоп-слова
    all_words = re.findall(r"[а-яёa-z0-9]{3,}", desc_lower)
    words = [w for w in all_words if w not in _STOP_WORDS]
    if not words:
        # Если после фильтрации ничего — вернуть оригинальные
        words = all_words
    if not words:
        return []

    conn = _ref_conn()
    try:
        results = []
        seen_codes = set()

        # ── Этап 1: AlphabeticalIndex (SearchName = UPPERCASE) ──
        for word in words[:5]:
            pattern = f"%{word.upper()}%"
            cursor = conn.execute(
                "SELECT Code, Name, SearchName FROM AlphabeticalIndex "
                "WHERE SearchName LIKE ? LIMIT 50",
                (pattern,),
            )
            for row in cursor.fetchall():
                code = row["Code"]
                if code in seen_codes or not code:
                    continue
                seen_codes.add(code)

                search_name = (row["SearchName"] or "").upper()
                name = row["Name"] or ""
                matched = [w for w in words if w.upper() in search_name]
                # Скоринг: каждое совпадение = 1 балл + бонус за длину слова
                score = sum(1 + len(w) / 10 for w in matched)
                if score > 0:
                    results.append({
                        "code": code,
                        "name": name,
                        "reasoning": f"Совпадение по алфавитному указателю: {', '.join(matched)}",
                        "score": score,
                        "source": "db",
                    })

        # ── Этап 2: TNVEDHead — Name/LongName (mixed case) ──
        for word in words[:5]:
            # SQLite LIKE — case-insensitive только для ASCII,
            # поэтому ищем и lowercase и uppercase для кириллицы
            lower_pat = f"%{word}%"
            upper_pat = f"%{word.upper()}%"
            title_pat = f"%{word.capitalize()}%"
            cursor = conn.execute(
                "SELECT Code, Name, LongName FROM TNVEDHead "
                "WHERE (Name LIKE ? OR Name LIKE ? OR Name LIKE ? "
                "       OR LongName LIKE ? OR LongName LIKE ? OR LongName LIKE ?) "
                "  AND (HasChild IS NULL OR HasChild = 0) "
                "LIMIT 30",
                (lower_pat, upper_pat, title_pat,
                 lower_pat, upper_pat, title_pat),
            )
            for row in cursor.fetchall():
                code = row["Code"]
                if code in seen_codes or not code or len(code) < 4:
                    continue
                seen_codes.add(code)

                name = row["Name"] or ""
                long_name = row["LongName"] or ""
                full_text = (name + " " + long_name).lower()
                matched = [w for w in words if w in full_text]
                score = sum(1 + len(w) / 10 for w in matched)
                # Бонус за 10-значный код (конечная позиция)
                if len(code) == 10:
                    score += 0.5
                if score > 0:
                    results.append({
                        "code": code,
                        "name": name,
                        "reasoning": f"Совпадение по названию ТН ВЭД: {', '.join(matched)}",
                        "score": score,
                        "source": "db",
                    })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_n]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 9. Скоринг совпадения кода с описанием
# ═══════════════════════════════════════════════════════════════

def score_code_match(code: str, product_description: str) -> Dict:
    verified = verify_code(code)
    if not verified:
        return {
            "score": 0,
            "max_score": 0,
            "details": [],
            "explanation": "Код отсутствует в справочнике — скоринг невозможен",
        }

    desc_lower = product_description.lower()
    code_desc = (verified["description"] + " " + verified.get("long_description", "")).lower()

    desc_words = set(re.findall(r"[а-яёa-z0-9]{3,}", desc_lower))
    code_words = set(re.findall(r"[а-яёa-z0-9]{3,}", code_desc))

    matched = desc_words & code_words
    noise = {"для", "или", "при", "что", "как", "это", "его", "они", "все", "них",
             "the", "and", "for", "with", "from", "прочие", "части", "другие",
             "том", "числе", "включая", "кроме", "также", "более", "менее"}
    matched -= noise

    score = len(matched)
    max_score = max(len(desc_words - noise), 1)
    details = []

    if matched:
        details.append(f"Совпавшие термины ({score}): {', '.join(sorted(matched)[:10])}")

    group_match = code[:4] in code_desc or code[:2] in code_desc
    if group_match:
        details.append("Группа/позиция совпадает")

    if score == 0:
        explanation = "Совпадений терминов не обнаружено"
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


# ═══════════════════════════════════════════════════════════════
# 10. Таможенный сбор (локальная БД, ПП РФ № 1637 ред. № 1638)
# ═══════════════════════════════════════════════════════════════

def get_customs_fee(customs_value: float) -> float:
    conn = _local_conn()
    try:
        cursor = conn.execute(
            "SELECT fee FROM customs_fees WHERE min_value <= ? AND max_value >= ? "
            "ORDER BY min_value LIMIT 1",
            (customs_value, customs_value),
        )
        row = cursor.fetchone()
        return row["fee"] if row else 73860.0
    finally:
        conn.close()


def get_customs_fee_range(customs_value: float) -> Optional[Dict]:
    conn = _local_conn()
    try:
        cursor = conn.execute(
            "SELECT min_value, max_value, fee FROM customs_fees "
            "WHERE min_value <= ? AND max_value >= ? ORDER BY min_value LIMIT 1",
            (customs_value, customs_value),
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


# ═══════════════════════════════════════════════════════════════
# 11. Статистика
# ═══════════════════════════════════════════════════════════════

def get_knowledge_base_stats() -> Dict:
    stats = {"hs_codes": 0, "preferences": 0, "customs_fees": 0, "rules": 18,
             "entrance_duty": 0, "vat_records": 0, "excise_records": 0,
             "countries": 0, "currency_rates": 0, "certificates": 0}

    if REF_DB_AVAILABLE:
        conn = _ref_conn()
        try:
            stats["hs_codes"] = conn.execute("SELECT COUNT(*) FROM TNVEDHead").fetchone()[0]
            stats["entrance_duty"] = conn.execute("SELECT COUNT(*) FROM EntranceDuty").fetchone()[0]
            stats["vat_records"] = conn.execute("SELECT COUNT(*) FROM VAT").fetchone()[0]
            stats["excise_records"] = conn.execute("SELECT COUNT(*) FROM Excise").fetchone()[0]
            stats["countries"] = conn.execute(
                "SELECT COUNT(DISTINCT AlphaCode) FROM WorldCountries WHERE AlphaCode IS NOT NULL"
            ).fetchone()[0]
            stats["certificates"] = conn.execute("SELECT COUNT(*) FROM SafetyCertificate").fetchone()[0]
        finally:
            conn.close()

    if USER_DB_AVAILABLE:
        conn = _user_conn()
        try:
            stats["currency_rates"] = conn.execute("SELECT COUNT(*) FROM CurrencyRates").fetchone()[0]
        finally:
            conn.close()

    try:
        conn = _local_conn()
        stats["customs_fees"] = conn.execute("SELECT COUNT(*) FROM customs_fees").fetchone()[0]
        conn.close()
    except Exception:
        stats["customs_fees"] = 8

    stats["preferences"] = stats["countries"]
    return stats
