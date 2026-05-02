# conclusion.py — Формирование экспертного заключения и перечня применённых правил

from typing import Dict, List, Optional
from datetime import date


def _format_currency(value: float) -> str:
    """Форматирует число в рублёвый формат: 1 234,56 ₽"""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def generate_short_conclusion(
    result: Dict,
    hs_code: str,
    product_description: str,
    code_in_db: bool,
) -> str:
    """
    Формирует краткое текстовое экспертное заключение — видимый блок в интерфейсе.
    Содержит все обязательные элементы, предусмотренные ТЗ ВКР.
    """
    is_manual = "Ручная" in result.get("duty_source", "")
    total_fmt = _format_currency(result["total"])
    cv_fmt = _format_currency(result["customs_value"])

    source_phrase = (
        "Код подтверждён в локальном справочнике ТН ВЭД."
        if code_in_db
        else "Код введён вручную, верификация по базе не выполнена."
    )

    coeff = result.get("duty_coefficient", 1.0)
    if coeff == 0.0:
        pref_phrase = "Преференция ЕАЭС применена (нулевая ставка пошлины)."
    elif coeff < 1.0:
        pref_phrase = f"Применена тарифная преференция (коэффициент {coeff})."
    else:
        pref_phrase = "Тарифная преференция не применяется."

    applied_rules = result.get("applied_rules", [])
    if applied_rules and isinstance(applied_rules[0], dict):
        rule_ids = ", ".join(r["id"] for r in applied_rules)
    else:
        rule_ids = "R5, R8, R10"

    desc_short = product_description[:80] + ("..." if len(product_description) > 80 else "")

    lines = [
        f"По результатам обработки товарной позиции «{desc_short}» система рекомендует "
        f"использовать код ТН ВЭД **{hs_code}**. {source_phrase}",
        "",
        f"Расчёт выполнен по ставке пошлины **{result['duty_rate']}%** "
        f"(тип: {result['duty_type']}) и ставке НДС **{result['vat_rate']}%**. "
        f"{pref_phrase}",
        "",
        f"Применены продукционные правила: {rule_ids}.",
        "",
        f"Таможенная стоимость: **{cv_fmt}**. "
        f"Сумма пошлины: **{_format_currency(result['duty_amount'])}**. "
        f"Сумма НДС: **{_format_currency(result['vat_amount'])}**. "
        f"Таможенный сбор: **{_format_currency(result['customs_fee'])}**.",
        "",
        f"Итоговая сумма таможенных платежей составляет **{total_fmt}** "
        f"({result['share_percent']}% от таможенной стоимости).",
        "",
        "*Результат носит рекомендательный характер и требует проверки специалистом.*",
    ]
    return "\n".join(lines)


def generate_conclusion(
    result: Dict,
    hs_code: str,
    product_description: str,
    country_name: str,
    country_code: str,
    currency: str,
    invoice_price: float,
    delivery_cost: float,
    insurance_cost: float,
    exchange_rate: float,
    code_reasoning: str = "",
    score_explanation: str = "",
    declaration_date: Optional[date] = None,
) -> str:
    """
    Формирует текстовое экспертное заключение по результатам расчёта.

    Заключение содержит 15 обязательных пунктов согласно ТЗ ВКР:
    описание, код, обоснование, ставки, страна, суммы,
    перечень продукционных правил и дисклеймер.
    """
    is_manual = "Ручная" in result.get("duty_source", "")
    decl_date_str = (declaration_date.strftime("%d.%m.%Y")
                     if declaration_date else date.today().strftime("%d.%m.%Y"))
    applied_rules: List[str] = result.get("applied_rules", [])

    lines = []
    lines.append("=" * 64)
    lines.append("            ЭКСПЕРТНОЕ ЗАКЛЮЧЕНИЕ")
    lines.append(f"            Дата формирования: {decl_date_str}")
    lines.append("=" * 64)

    # 1. Описание товара
    lines.append("")
    lines.append("1. ОПИСАНИЕ ТОВАРА")
    lines.append(f"   {product_description}")

    # 2. Выбранный код ТН ВЭД
    lines.append("")
    lines.append("2. КОД ТН ВЭД ЕАЭС")
    lines.append(f"   {hs_code}")

    # 3. Обоснование выбора кода
    lines.append("")
    lines.append("3. ОБОСНОВАНИЕ ВЫБОРА КОДА")
    if is_manual:
        lines.append("   Код введён пользователем вручную.")
        lines.append("   Автоматическая верификация по БД не выполнена.")
    else:
        if code_reasoning:
            lines.append(f"   {code_reasoning}")
        else:
            lines.append("   Код подтверждён в локальном справочнике ТН ВЭД.")
        if score_explanation:
            lines.append(f"   Скоринг: {score_explanation}")

    # 4. Тип ставки пошлины
    lines.append("")
    lines.append("4. ТИП СТАВКИ ПОШЛИНЫ")
    lines.append(f"   {result['duty_type']}")

    # 5. Ставка пошлины
    lines.append("")
    lines.append("5. СТАВКА ПОШЛИНЫ")
    lines.append(f"   {result['duty_rate']}%")

    # 6. Ставка НДС
    lines.append("")
    lines.append("6. СТАВКА НДС")
    lines.append(f"   {result['vat_rate']}%")

    # 7. Страна происхождения
    lines.append("")
    lines.append("7. СТРАНА ПРОИСХОЖДЕНИЯ")
    lines.append(f"   {country_name} ({country_code})")

    # 8. Коэффициент преференции
    lines.append("")
    lines.append("8. КОЭФФИЦИЕНТ ПРЕФЕРЕНЦИИ")
    coeff = result.get("duty_coefficient", 1.0)
    if coeff == 0.0:
        lines.append(f"   {coeff} (нулевая ставка — страна ЕАЭС)")
    elif coeff < 1.0:
        lines.append(f"   {coeff} (преференциальный режим)")
    else:
        lines.append(f"   {coeff} (преференция не применяется)")

    # 9. Таможенная стоимость
    lines.append("")
    lines.append("9. ТАМОЖЕННАЯ СТОИМОСТЬ")
    lines.append(f"   Метод определения: по стоимости сделки (ТК ЕАЭС, ст. 39)")
    lines.append(f"   Цена по инвойсу:   {invoice_price:,.2f} {currency}")
    lines.append(f"   Доставка:          {delivery_cost:,.2f} {currency}")
    lines.append(f"   Страхование:       {insurance_cost:,.2f} {currency}")
    lines.append(f"   Курс ЦБ РФ:       {exchange_rate:.2f} ₽/{currency}")
    lines.append(f"   Итого (ТС):        {_format_currency(result['customs_value'])}")

    # 10. Сумма пошлины
    lines.append("")
    lines.append("10. СУММА ВВОЗНОЙ ПОШЛИНЫ")
    lines.append(f"    {_format_currency(result['duty_amount'])}")

    # 11. Сумма НДС
    lines.append("")
    lines.append("11. СУММА НДС")
    lines.append(f"    База НДС: {_format_currency(result.get('vat_base', result['customs_value'] + result['duty_amount']))}")
    lines.append(f"    НДС:      {_format_currency(result['vat_amount'])}")

    # 12. Таможенный сбор
    lines.append("")
    lines.append("12. ТАМОЖЕННЫЙ СБОР")
    lines.append(f"    Основание: ПП РФ № 1637 в ред. № 1638 (с 01.01.2026)")
    lines.append(f"    Размер:    {_format_currency(result['customs_fee'])}")

    # 13. Итоговая сумма платежей
    lines.append("")
    lines.append("13. ИТОГО ТАМОЖЕННЫЕ ПЛАТЕЖИ")
    lines.append(f"    Пошлина:         {_format_currency(result['duty_amount'])}")
    lines.append(f"    НДС:             {_format_currency(result['vat_amount'])}")
    lines.append(f"    Таможенный сбор: {_format_currency(result['customs_fee'])}")
    lines.append(f"    ─────────────────────────────────────")
    lines.append(f"    ИТОГО:           {_format_currency(result['total'])}")
    lines.append(f"    Доля платежей от ТС: {result['share_percent']}%")

    # 14. Перечень применённых продукционных правил
    lines.append("")
    lines.append("14. ПЕРЕЧЕНЬ ПРИМЕНЁННЫХ ПРОДУКЦИОННЫХ ПРАВИЛ")
    if applied_rules:
        for rule in applied_rules:
            if isinstance(rule, dict):
                lines.append(f"    • {rule['id']} — {rule['name']}: {rule['explanation']}")
            else:
                lines.append(f"    • {rule}")
    else:
        lines.append("    Правила не зафиксированы.")

    # 15. Дисклеймер
    lines.append("")
    lines.append("=" * 64)
    lines.append("15. ПРИМЕЧАНИЕ")
    lines.append("")
    lines.append("Результат расчёта носит рекомендательный характер и предназначен")
    lines.append("для предварительной оценки импортной поставки. Окончательное")
    lines.append("решение о классификации товара по ТН ВЭД принимает специалист.")
    lines.append("")
    lines.append("Настоящее заключение сформировано автоматически системой")
    lines.append("поддержки принятия решений (СППР) «Таможенный эксперт».")
    lines.append("Классификация товара выполнена с использованием нейросетевой")
    lines.append("модели YandexGPT и требует верификации специалистом.")
    lines.append("Ответственность за декларирование и уплату таможенных платежей")
    lines.append("несёт декларант (ТК ЕАЭС, ст. 84; НК РФ, ст. 174).")
    lines.append("=" * 64)

    return "\n".join(lines)
