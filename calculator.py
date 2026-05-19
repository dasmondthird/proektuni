# calculator.py — Расчёт таможенных платежей с фиксацией продукционных правил
#
# 18 продукционных правил экспертной подсистемы (глава 2.3 ВКР):
#   R1–R4:   определение преференциального режима
#   R5–R7:   расчёт ввозной таможенной пошлины
#   R8–R9:   формирование налоговой базы НДС
#   R10:     расчёт НДС
#   R11–R18: определение таможенного сбора (ПП РФ № 1637 ред. № 1638)

from typing import Dict, List

from verifier import (
    get_duty_info, get_preference_coefficient, get_preference_info,
    get_customs_fee, get_customs_fee_range, get_currency_rate,
)


class UnverifiedCodeError(Exception):
    pass


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _rule(rule_id: str, name: str, explanation: str) -> Dict:
    return {"id": rule_id, "name": name, "explanation": explanation}


def _calc_rate_amount(
    rate_value: float,
    rate_sign: str,
    customs_value: float,
    base_quantity: float,
    eur_rate: float,
    usd_rate: float,
) -> float:
    if rate_value is None or rate_value == 0:
        return 0.0
    if rate_sign == "%":
        return customs_value * rate_value / 100.0
    elif rate_sign == "978":
        return rate_value * base_quantity * eur_rate
    elif rate_sign == "840":
        return rate_value * base_quantity * usd_rate
    elif rate_sign == "643":
        return rate_value * base_quantity
    return customs_value * rate_value / 100.0


def calculate_all_payments(
    invoice_price: float,
    delivery_cost: float,
    insurance_cost: float,
    exchange_rate: float,
    hs_code: str,
    country_code: str,
    weight: float = 0.0,
    eur_rate: float = 1.0,
    usd_rate: float = 1.0,
    allow_unverified: bool = False,
    manual_duty_rate: float = 0.0,
    manual_vat_rate: float = 0.0,
    ref_date: str = None,
) -> Dict:
    rules: List[Dict] = []

    # ── Таможенная стоимость (метод 1 — по стоимости сделки) ──
    customs_value = (invoice_price + delivery_cost + insurance_cost) * exchange_rate
    customs_value = round(customs_value, 2)
    cv_explanation = (
        f"ТС = ({_fmt(invoice_price)} + {_fmt(delivery_cost)} + {_fmt(insurance_cost)}) "
        f"× {exchange_rate:.4f} = {_fmt(customs_value)} ₽"
    )

    # ── Получение ставок из базы знаний ──
    duty_info = get_duty_info(hs_code, ref_date=ref_date)
    is_manual = False
    if duty_info is None:
        if not allow_unverified:
            raise UnverifiedCodeError(
                f"Код {hs_code} не найден в справочнике. "
                f"Расчёт невозможен без верифицированного кода."
            )
        is_manual = True
        duty_info = {
            "duty_type": "адвалорная",
            "duty_rate": manual_duty_rate,
            "rate_sign": "%",
            "rate_unit": None,
            "add_rate": None,
            "add_rate_sign": None,
            "add_rate_unit": None,
            "alt_rate": None,
            "alt_rate_sign": None,
            "alt_rate_unit": None,
            "vat_rate": manual_vat_rate,
            "excise": 0,
            "source": "Ручная верификация пользователем (код вне справочника)",
        }
    source = duty_info["source"]

    duty_rate = duty_info["duty_rate"]
    duty_type = duty_info["duty_type"]
    vat_rate = duty_info["vat_rate"]
    excise = duty_info["excise"]

    rate_sign = duty_info.get("rate_sign", "%")
    add_rate = duty_info.get("add_rate")
    add_rate_sign = duty_info.get("add_rate_sign")
    alt_rate = duty_info.get("alt_rate")
    alt_rate_sign = duty_info.get("alt_rate_sign")

    # ═══════════════════════════════════════════════════════════
    # БЛОК 1: Преференциальный режим (R1–R4)
    # ═══════════════════════════════════════════════════════════
    pref_info = get_preference_info(country_code)
    coefficient = pref_info["coefficient"] if pref_info else 1.0

    if pref_info and coefficient == 0.0:
        rules.append(_rule(
            "R1", "Нулевая ставка (ЕАЭС / наименее развитая)",
            f"Страна {pref_info['country_name']} ({country_code}) — {pref_info['preference_type']} → "
            f"коэффициент = 0 (пошлина не взимается)"
        ))
    elif pref_info and coefficient < 1.0:
        rules.append(_rule(
            "R2", "Преференциальный режим",
            f"Страна {pref_info['country_name']} ({country_code}) — {pref_info['preference_type']} → "
            f"коэффициент = {coefficient}"
        ))
    elif pref_info and coefficient == 1.0:
        rules.append(_rule(
            "R3", "Базовый режим",
            f"Страна {pref_info['country_name']} ({country_code}) — базовый тарифный "
            f"режим → коэффициент = 1,0"
        ))
    else:
        rules.append(_rule(
            "R4", "Преференция не определена",
            f"Страна {country_code} отсутствует в справочнике преференций → "
            f"коэффициент = 1,0 (полная ставка по умолчанию)"
        ))

    # ═══════════════════════════════════════════════════════════
    # БЛОК 2: Расчёт ввозной таможенной пошлины (R5–R7)
    # ═══════════════════════════════════════════════════════════
    base_quantity = weight if weight > 0 else 1.0

    if duty_type == "адвалорная":
        duty_amount = customs_value * duty_rate * coefficient / 100
        rules.append(_rule(
            "R5", "Адвалорная пошлина",
            f"Пошлина = ТС × ставка × коэфф / 100 = "
            f"{_fmt(customs_value)} × {duty_rate}% × {coefficient} / 100 = {_fmt(duty_amount)} ₽"
        ))

    elif duty_type == "специфическая":
        currency_mul = eur_rate if rate_sign == "978" else (usd_rate if rate_sign == "840" else 1.0)
        duty_amount = duty_rate * base_quantity * currency_mul
        currency_name = {"978": "EUR", "840": "USD", "643": "RUB"}.get(rate_sign, "")
        rules.append(_rule(
            "R6", "Специфическая пошлина",
            f"Пошлина = ставка × кол-во × курс = "
            f"{duty_rate} {currency_name} × {base_quantity} × {currency_mul:.4f} = {_fmt(duty_amount)} ₽"
        ))

    elif duty_type == "комбинированная":
        ad_valorem = customs_value * duty_rate * coefficient / 100

        add_amount = 0.0
        if add_rate is not None and add_rate > 0:
            add_amount = _calc_rate_amount(
                add_rate, add_rate_sign or rate_sign,
                customs_value, base_quantity, eur_rate, usd_rate,
            )

        main_sum = ad_valorem + add_amount

        alt_amount = 0.0
        if alt_rate is not None and alt_rate > 0:
            alt_amount = _calc_rate_amount(
                alt_rate, alt_rate_sign or rate_sign,
                customs_value, base_quantity, eur_rate, usd_rate,
            )

        if alt_amount > 0 and alt_amount > main_sum:
            duty_amount = alt_amount
            rules.append(_rule(
                "R7", "Комбинированная пошлина (альтернативная ставка)",
                f"max(основная {_fmt(main_sum)}, альтернативная {_fmt(alt_amount)}) "
                f"= {_fmt(duty_amount)} ₽ (применена альтернативная «но не менее»)"
            ))
        else:
            duty_amount = main_sum
            rules.append(_rule(
                "R7", "Комбинированная пошлина (основная ставка)",
                f"max(основная {_fmt(main_sum)}, альтернативная {_fmt(alt_amount)}) "
                f"= {_fmt(duty_amount)} ₽ (применена основная)"
            ))
    else:
        duty_amount = customs_value * duty_rate * coefficient / 100
        rules.append(_rule(
            "R5", "Пошлина",
            f"Пошлина = ТС × ставка × коэфф / 100 = "
            f"{_fmt(customs_value)} × {duty_rate}% × {coefficient} / 100 = {_fmt(duty_amount)} ₽"
        ))

    duty_amount = round(duty_amount, 2)

    # ═══════════════════════════════════════════════════════════
    # БЛОК 3: Налоговая база НДС (R8–R9)
    # ═══════════════════════════════════════════════════════════
    vat_base = customs_value + duty_amount + excise
    if excise > 0:
        rules.append(_rule(
            "R9", "Товар подакцизный",
            f"База НДС = ТС + пошлина + акциз = "
            f"{_fmt(customs_value)} + {_fmt(duty_amount)} + {_fmt(excise)} = {_fmt(vat_base)} ₽"
        ))
    else:
        rules.append(_rule(
            "R8", "Товар не подакцизный",
            f"База НДС = ТС + пошлина = "
            f"{_fmt(customs_value)} + {_fmt(duty_amount)} = {_fmt(vat_base)} ₽"
        ))

    # ═══════════════════════════════════════════════════════════
    # БЛОК 4: Расчёт НДС (R10)
    # ═══════════════════════════════════════════════════════════
    vat_amount = round(vat_base * vat_rate / 100, 2)
    rules.append(_rule(
        "R10", "Расчёт НДС",
        f"НДС = база × {vat_rate}% / 100 = "
        f"{_fmt(vat_base)} × {vat_rate} / 100 = {_fmt(vat_amount)} ₽"
    ))

    # ═══════════════════════════════════════════════════════════
    # БЛОК 5: Таможенный сбор по диапазону ТС (R11–R18)
    # ═══════════════════════════════════════════════════════════
    customs_fee = get_customs_fee(customs_value)
    fee_range = get_customs_fee_range(customs_value)

    _FEE_RULE_MAP = {
        1231.0:  ("R11", "ТС ≤ 200 000 ₽"),
        2462.0:  ("R12", "200 000 < ТС ≤ 450 000 ₽"),
        4924.0:  ("R13", "450 000 < ТС ≤ 1 200 000 ₽"),
        13541.0: ("R14", "1 200 000 < ТС ≤ 2 700 000 ₽"),
        18465.0: ("R15", "2 700 000 < ТС ≤ 4 200 000 ₽"),
        21344.0: ("R16", "4 200 000 < ТС ≤ 5 500 000 ₽"),
        49240.0: ("R17", "5 500 000 < ТС ≤ 10 000 000 ₽"),
        73860.0: ("R18", "ТС > 10 000 000 ₽"),
    }

    fee_rule_id, fee_range_label = _FEE_RULE_MAP.get(
        customs_fee, ("R18", "ТС > 10 000 000 ₽")
    )
    if fee_range:
        rules.append(_rule(
            fee_rule_id, f"Таможенный сбор ({fee_range_label})",
            f"ТС = {_fmt(customs_value)} ₽ попадает в диапазон "
            f"{_fmt(fee_range['min_value'])} – {_fmt(fee_range['max_value'])} ₽ → "
            f"сбор = {_fmt(customs_fee)} ₽ (ПП РФ № 1637 ред. № 1638)"
        ))
    else:
        rules.append(_rule(
            "R18", f"Таможенный сбор ({fee_range_label})",
            f"ТС = {_fmt(customs_value)} ₽ превышает все диапазоны → "
            f"максимальный сбор = {_fmt(customs_fee)} ₽"
        ))

    # ── Итог ──
    total = round(duty_amount + vat_amount + customs_fee, 2)
    share_percent = round(total / customs_value * 100, 2) if customs_value > 0 else 0.0

    return {
        "customs_value": customs_value,
        "cv_explanation": cv_explanation,
        "duty_type": duty_type,
        "duty_rate": duty_rate,
        "rate_sign": rate_sign,
        "duty_coefficient": coefficient,
        "duty_amount": duty_amount,
        "duty_source": source,
        "vat_rate": vat_rate,
        "vat_base": vat_base,
        "vat_amount": vat_amount,
        "excise": excise,
        "customs_fee": customs_fee,
        "total": total,
        "share_percent": share_percent,
        "applied_rules": rules,
        "applied_rule_ids": [r["id"] for r in rules],
    }
