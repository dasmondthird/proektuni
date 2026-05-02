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
    get_customs_fee, get_customs_fee_range,
)


class UnverifiedCodeError(Exception):
    """Код ТН ВЭД не найден в справочнике — расчёт недопустим без подтверждения."""
    pass


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _rule(rule_id: str, name: str, explanation: str) -> Dict:
    return {"id": rule_id, "name": name, "explanation": explanation}


def calculate_all_payments(
    invoice_price: float,
    delivery_cost: float,
    insurance_cost: float,
    exchange_rate: float,
    hs_code: str,
    country_code: str,
    weight: float = 0.0,
    eur_rate: float = 1.0,
    allow_unverified: bool = False,
    manual_duty_rate: float = 0.0,
    manual_vat_rate: float = 0.0,
) -> Dict:
    """
    Полный расчёт всех таможенных платежей.

    Возвращает словарь с суммами и перечнем applied_rules — списком словарей
    {"id": "R5", "name": "Адвалорная пошлина", "explanation": "..."},
    привязанных к 18 продукционным правилам экспертной подсистемы.
    """
    rules: List[Dict] = []

    # ── Предварительный этап: таможенная стоимость (метод 1 — по стоимости сделки) ──
    customs_value = (invoice_price + delivery_cost + insurance_cost) * exchange_rate
    customs_value = round(customs_value, 2)
    cv_explanation = (
        f"ТС = ({_fmt(invoice_price)} + {_fmt(delivery_cost)} + {_fmt(insurance_cost)}) "
        f"× {exchange_rate:.2f} = {_fmt(customs_value)} ₽"
    )

    # ── Получение ставок из базы знаний ──
    duty_info = get_duty_info(hs_code)
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
            "vat_rate": manual_vat_rate,
            "excise": 0,
            "source": "Ручная верификация пользователем (код вне справочника)",
        }
    source = duty_info["source"]

    duty_rate = duty_info["duty_rate"]
    duty_type = duty_info["duty_type"]
    vat_rate = duty_info["vat_rate"]
    excise = duty_info["excise"]

    # ══════════════════════════════════════════════════════════════
    # БЛОК 1: Преференциальный режим (R1–R4)
    # ══════════════════════════════════════════════════════════════
    pref_info = get_preference_info(country_code)
    coefficient = pref_info["coefficient"] if pref_info else 1.0

    if pref_info and coefficient == 0.0:
        rules.append(_rule(
            "R1", "Нулевая ставка (ЕАЭС)",
            f"Страна {pref_info['country_name']} ({country_code}) входит в ЕАЭС → "
            f"коэффициент = 0 (пошлина не взимается)"
        ))
    elif pref_info and coefficient < 1.0:
        rules.append(_rule(
            "R2", "Преференциальный режим",
            f"Страна {pref_info['country_name']} ({country_code}) имеет преференциальное "
            f"соглашение → коэффициент = {coefficient}"
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

    # ══════════════════════════════════════════════════════════════
    # БЛОК 2: Расчёт ввозной таможенной пошлины (R5–R7)
    # ══════════════════════════════════════════════════════════════
    if duty_type == "адвалорная":
        duty_amount = customs_value * duty_rate * coefficient / 100
        rules.append(_rule(
            "R5", "Адвалорная пошлина",
            f"Пошлина = ТС × ставка × коэфф / 100 = "
            f"{_fmt(customs_value)} × {duty_rate} × {coefficient} / 100 = {_fmt(duty_amount)} ₽"
        ))
    elif duty_type == "специфическая":
        duty_amount = weight * duty_rate * eur_rate
        rules.append(_rule(
            "R6", "Специфическая пошлина",
            f"Пошлина = вес × ставка × курс EUR = "
            f"{weight} × {duty_rate} × {eur_rate:.2f} = {_fmt(duty_amount)} ₽"
        ))
    else:
        ad_valorem = customs_value * duty_rate * coefficient / 100
        specific = weight * duty_rate * eur_rate
        duty_amount = max(ad_valorem, specific)
        rules.append(_rule(
            "R7", "Комбинированная пошлина",
            f"Пошлина = max(адвалорная {_fmt(ad_valorem)}, специфическая {_fmt(specific)}) "
            f"= {_fmt(duty_amount)} ₽"
        ))
    duty_amount = round(duty_amount, 2)

    # ══════════════════════════════════════════════════════════════
    # БЛОК 3: Налоговая база НДС (R8–R9)
    # ══════════════════════════════════════════════════════════════
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

    # ══════════════════════════════════════════════════════════════
    # БЛОК 4: Расчёт НДС (R10)
    # ══════════════════════════════════════════════════════════════
    vat_amount = round(vat_base * vat_rate / 100, 2)
    rules.append(_rule(
        "R10", "Расчёт НДС",
        f"НДС = база × {vat_rate}% / 100 = "
        f"{_fmt(vat_base)} × {vat_rate} / 100 = {_fmt(vat_amount)} ₽"
    ))

    # ══════════════════════════════════════════════════════════════
    # БЛОК 5: Таможенный сбор по диапазону ТС (R11–R18)
    # ══════════════════════════════════════════════════════════════
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
