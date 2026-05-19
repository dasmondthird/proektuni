# app.py — Streamlit-интерфейс системы «Таможенный эксперт»
# Запуск: streamlit run app.py

import csv
import io
import os
from datetime import datetime, date

import streamlit as st

from classifier import classify_product
from verifier import (
    verify_code, get_duty_info, get_all_countries,
    get_customs_fee, get_preference_coefficient,
    score_code_match, find_codes_by_description,
    get_knowledge_base_stats, get_latest_rates,
    get_currency_rate, update_currency_rates_from_cbr,
)
from calculator import calculate_all_payments, UnverifiedCodeError
from conclusion import generate_conclusion, generate_short_conclusion
from evaluation import calculate_metrics
from config import DB_PATH, BASE_DIR, YANDEX_API_KEY, REF_DB_AVAILABLE, USER_DB_AVAILABLE


# ──────────────────────────────────────────────────────────────
# Настройка страницы
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Таможенный эксперт — ТН ВЭД ЕАЭС",
    page_icon="🛃",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown("""<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.stDeployButton {display: none;}
</style>""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────
# Инициализация БД
# ──────────────────────────────────────────────────────────────
def ensure_database():
    if not os.path.exists(DB_PATH):
        try:
            from init_db import init_database
            init_database()
            st.rerun()
        except Exception as e:
            st.error(f"❌ Ошибка инициализации локальной БД: {e}")
            st.stop()

ensure_database()

if not REF_DB_AVAILABLE:
    st.warning(
        "⚠️ Профессиональный справочник CustomsReference.DB не найден. "
        "Система работает с ограниченной базой данных. "
        "Скачайте справочник и укажите путь в переменной CUSTOMS_DATA_DIR."
    )


# ──────────────────────────────────────────────────────────────
# Сайдбар: статистика базы знаний и метрики тестирования
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📊 База знаний")
    kb = get_knowledge_base_stats()
    src_label = "CustomsReference.DB" if REF_DB_AVAILABLE else "локальная (ограниченная)"
    st.caption(f"Источник: {src_label}")
    st.markdown(
        f"- ✅ Коды ТН ВЭД: **{kb['hs_codes']:,}** записей\n"
        f"- ✅ Ставки пошлин: **{kb['entrance_duty']:,}** записей\n"
        f"- ✅ Ставки НДС: **{kb['vat_records']:,}** записей\n"
        f"- ✅ Акцизы: **{kb['excise_records']:,}** записей\n"
        f"- ✅ Страны: **{kb['countries']}**\n"
        f"- ✅ Курсы валют: **{kb['currency_rates']:,}** записей\n"
        f"- ✅ Сертификаты: **{kb['certificates']:,}** записей\n"
        f"- ✅ Таможенные сборы: **{kb['customs_fees']}** диапазонов\n"
        f"- ✅ Продукционные правила: **{kb['rules']}**"
    )

    if USER_DB_AVAILABLE:
        st.markdown("---")
        st.header("💱 Курсы валют ЦБ РФ")
        for code in ("USD", "EUR", "CNY"):
            ri = get_currency_rate(code)
            if ri:
                st.caption(f"{code}: **{ri['rate']:.4f}** ₽ ({ri['date']})")
        if st.button("🔄 Обновить курсы", key="update_rates"):
            ok = update_currency_rates_from_cbr()
            if ok:
                st.success("✅ Курсы обновлены")
                st.session_state.currency_rates_loaded = False
                st.rerun()
            else:
                st.info("Нет новых данных или ошибка подключения к ЦБ РФ")

    st.markdown("---")
    st.header("🧪 Метрики тестирования")
    metrics = calculate_metrics()
    if metrics["total_tests"] > 0:
        st.markdown(
            f"- Количество тестов: **{metrics['total_tests']}**\n"
            f"- Top-3 accuracy: **{metrics['top3_accuracy']}%**\n"
            f"- Код найден в БД: **{metrics['codes_found_in_db']}** "
            f"({metrics['db_coverage']}%)\n"
            f"- Среднее ручное время: **{metrics['avg_manual_time']}** мин\n"
            f"- Среднее время системы: **{metrics['avg_system_time']}** мин\n"
            f"- Экономия на позицию: **{metrics['time_saved']}** мин"
        )
    else:
        st.caption("Результаты тестирования пока отсутствуют.")


# ──────────────────────────────────────────────────────────────
# CSV-логирование
# ──────────────────────────────────────────────────────────────
TEST_RESULTS_PATH = os.path.join(BASE_DIR, "test_results.csv")
TEST_CSV_FIELDS = [
    "date", "product_description", "expected_code", "suggested_codes",
    "selected_code", "code_found_in_db", "customs_value", "duty",
    "vat", "fee", "total_payment", "manual_time_min",
    "system_time_min", "result_comment",
]


def _ensure_csv_header():
    if not os.path.exists(TEST_RESULTS_PATH):
        with open(TEST_RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=TEST_CSV_FIELDS, delimiter=";").writeheader()


def save_test_result(row: dict):
    _ensure_csv_header()
    with open(TEST_RESULTS_PATH, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=TEST_CSV_FIELDS, delimiter=";").writerow(row)


def result_to_csv_bytes(result: dict, hs_code: str, description: str,
                         country_name: str, currency: str) -> bytes:
    rows = [
        ["Параметр", "Значение"],
        ["Код ТН ВЭД", hs_code],
        ["Описание товара", description],
        ["Страна происхождения", country_name],
        ["Валюта инвойса", currency],
        [""],
        ["Таможенная стоимость (руб.)", result["customs_value"]],
        ["Тип пошлины", result["duty_type"]],
        ["Ставка пошлины (%)", result["duty_rate"]],
        ["Коэффициент преференции", result["duty_coefficient"]],
        ["Сумма пошлины (руб.)", result["duty_amount"]],
        ["Ставка НДС (%)", result["vat_rate"]],
        ["Сумма НДС (руб.)", result["vat_amount"]],
        ["Таможенный сбор (руб.)", result["customs_fee"]],
        [""],
        ["ИТОГО платежей (руб.)", result["total"]],
        ["Доля платежей от ТС (%)", result["share_percent"]],
        [""],
        ["Применённые правила"],
    ]
    for r in result.get("applied_rules", []):
        if isinstance(r, dict):
            rows.append([f"{r['id']} — {r['name']}: {r['explanation']}"])
        else:
            rows.append([r])
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _format_duty_rate(info: dict) -> str:
    """Форматирование ставки пошлины с учётом типа (адвалорная/специфическая)."""
    rate = info.get("duty_rate", 0)
    dtype = info.get("duty_type", "адвалорная")
    # Для verify_code результата нет rate_sign, нужно определить по duty_type
    if dtype == "специфическая":
        # Получаем из get_duty_info для точного rate_sign
        di = get_duty_info(info.get("code", ""))
        if di:
            sign = di.get("rate_sign", "%")
            if sign == "978":
                return f"{rate} EUR/ед. ({dtype})"
            elif sign == "840":
                return f"{rate} USD/ед. ({dtype})"
            elif sign == "643":
                return f"{rate} ₽/ед. ({dtype})"
        return f"{rate} ед. ({dtype})"
    elif dtype == "комбинированная":
        return f"{rate}% + спец. ({dtype})"
    return f"{rate}% ({dtype})"


# ──────────────────────────────────────────────────────────────
# Вспомогательная функция: объединить LLM-коды и коды из БД
# ──────────────────────────────────────────────────────────────
def _merge_results(llm_results: list, db_results: list) -> list:
    """
    Объединяет результаты LLM и локального поиска.
    Коды из БД идут первыми (они верифицированы).
    Дубликаты удаляются — если LLM предложил тот же код, что нашла БД,
    в финальный список он попадает один раз с пометкой 'both'.
    """
    merged = []
    db_codes = set()

    for r in db_results:
        r = dict(r)
        r["source"] = "db"
        merged.append(r)
        db_codes.add(r["code"])

    for r in llm_results:
        r = dict(r)
        if r["code"] in db_codes:
            for m in merged:
                if m["code"] == r["code"]:
                    m["source"] = "both"
                    m["llm_reasoning"] = r.get("reasoning", "")
        else:
            r["source"] = "llm"
            merged.append(r)

    return merged[:5]  # показываем не более 5 вариантов


# ──────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────
_DEFAULTS = {
    "classification_results": None,
    "positions": [],
    "calculation_done": False,
    "last_calculation": None,
    "last_code": "",
    "last_description": "",
    "last_reasoning": "",
    "last_score_info": None,
    "api_unavailable": False,
    "desc_area": "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

_DEFAULT_RATES = {"USD": 92.50, "EUR": 100.00, "CNY": 12.50}
if "currency_rates_loaded" not in st.session_state:
    live = get_latest_rates()
    st.session_state.currency_rates_loaded = True
    st.session_state.live_rates = live if live else {}
CURRENCY_RATES = {**_DEFAULT_RATES, **st.session_state.get("live_rates", {})}


# ──────────────────────────────────────────────────────────────
# Заголовок
# ──────────────────────────────────────────────────────────────
st.title("🛃 Таможенный эксперт")
st.caption("Интеллектуальная экспертная система поддержки предварительного подбора "
           "кода ТН ВЭД ЕАЭС и расчёта таможенных платежей")

with st.expander("ℹ️ Алгоритм работы с системой", expanded=False):
    st.markdown("""
1. Введите описание товара и параметры поставки.
2. Нажмите **«Получить варианты кода»** — система выполнит поиск по локальной базе знаний и при наличии ключа обратится к внешнему NLP-модулю.
3. Выберите подходящий код из предложенных вариантов (или введите вручную).
4. Нажмите **«Рассчитать платежи»**.
5. Проверьте калькуляцию, применённые правила и экспертное заключение.

> Внешний NLP-модуль используется только для предварительной рекомендации. Финансовые расчёты выполняются детерминированным модулем по данным локальной базы знаний.
""")


# ──────────────────────────────────────────────────────────────
# БЛОК 1: Описание товара и параметры поставки
# ──────────────────────────────────────────────────────────────
st.subheader("📋 1. Описание товара и параметры поставки")

_EXAMPLES = [
    ("🔧 Колодки тормозные",
     "Тормозные колодки керамические для Toyota Camry, комплект 4 шт."),
    ("🌀 Воздушный фильтр",
     "Фильтр воздушный для двигателя легкового автомобиля"),
    ("🔩 Амортизатор",
     "Амортизатор передний газомасляный для Hyundai Solaris"),
    ("⚡ Свечи зажигания",
     "Свеча зажигания иридиевая для бензинового двигателя"),
    ("⚙️ Подшипник ступицы",
     "Подшипник ступицы передний шариковый для Renault Logan"),
]

st.caption("Быстрые примеры:")
_ex_cols = st.columns(len(_EXAMPLES))
for _col, (_label, _text) in zip(_ex_cols, _EXAMPLES):
    with _col:
        if st.button(_label, use_container_width=True):
            st.session_state.desc_area = _text
            st.rerun()

product_description = st.text_area(
    "Описание товара (из инвойса или по шаблону)",
    placeholder="Например: Колодки тормозные керамические для Toyota Camry, комплект 4 шт.",
    height=100,
    key="desc_area",
)


# ── Параметры поставки ──

col_country, col_currency = st.columns(2)
with col_country:
    countries = get_all_countries()
    priority = ["CN", "TR", "KR", "DE", "JP"]
    sorted_countries = sorted(
        countries,
        key=lambda c: (c[0] not in priority,
                       priority.index(c[0]) if c[0] in priority else 999, c[1]),
    )
    country_options = {f"{name} ({code})": code for code, name, _ in sorted_countries}
    country_labels = list(country_options.keys())
    selected_country_label = st.selectbox("Страна происхождения", country_labels, key="country_select")
    selected_country_code = country_options[selected_country_label]

with col_currency:
    currency = st.selectbox("Валюта инвойса", ["USD", "EUR", "CNY"], key="currency_select")

col_price, col_delivery, col_insurance = st.columns(3)
with col_price:
    invoice_price = st.number_input("Цена товара", min_value=0.0, value=0.0,
                                    format="%.2f", key="price")
with col_delivery:
    delivery_cost = st.number_input("Стоимость доставки", min_value=0.0, value=0.0,
                                    format="%.2f", key="delivery")
with col_insurance:
    insurance_cost = st.number_input("Стоимость страхования", min_value=0.0, value=0.0,
                                     format="%.2f", key="insurance")

col_rate, col_date = st.columns(2)
with col_rate:
    default_rate = CURRENCY_RATES.get(currency, 1.0)
    rate_hint = ""
    rate_info = get_currency_rate(currency) if USER_DB_AVAILABLE else None
    if rate_info:
        rate_hint = f" (ЦБ РФ на {rate_info['date']})"
        default_rate = round(rate_info["rate"], 4)
    exchange_rate = st.number_input(
        f"Курс ЦБ РФ (₽ за 1 {currency}){rate_hint}", min_value=0.01,
        value=default_rate, format="%.4f", key=f"rate_{currency}",
    )
with col_date:
    declaration_date = st.date_input(
        "Дата декларирования",
        value=date(2026, 3, 24),
        key="decl_date",
    )
ref_date = declaration_date.isoformat()

all_filled = bool(
    (product_description or "").strip()
    and selected_country_code
    and invoice_price > 0
    and exchange_rate > 0
)
api_key_ok = bool(YANDEX_API_KEY)


# ──────────────────────────────────────────────────────────────
# БЛОК 2: Подбор и проверка кода ТН ВЭД
# ──────────────────────────────────────────────────────────────
st.subheader("🔍 2. Подбор и проверка кода ТН ВЭД")

if not api_key_ok:
    st.info("ℹ️ Внешний NLP-модуль не подключён — используется только локальный поиск по базе знаний.")

btn_col1, btn_col2 = st.columns(2)
with btn_col1:
    classify_btn = st.button(
        "🔍 Получить варианты кода ТН ВЭД",
        type="primary",
        use_container_width=True,
        disabled=not all_filled,
        help="Поиск по локальной базе знаний + внешний NLP-модуль (если подключён)",
    )
with btn_col2:
    manual_mode_btn = st.button(
        "✏️ Ввести код вручную",
        use_container_width=True,
        disabled=not all_filled,
    )

if classify_btn and all_filled:
    desc = (product_description or "").strip()
    db_results = find_codes_by_description(desc, top_n=3)
    llm_results = []

    if api_key_ok:
        with st.spinner("Запрос к внешнему NLP-модулю..."):
            try:
                llm_results = classify_product(desc)
            except ConnectionError as e:
                st.warning(f"🌐 Внешний NLP-модуль недоступен: {e}\nИспользуются результаты из локальной базы.")
            except ValueError as e:
                try:
                    llm_results = classify_product(desc)
                except Exception:
                    st.warning("⚠️ Внешний NLP-модуль вернул невалидный ответ. Используется локальный поиск.")
            except Exception as e:
                st.warning(f"⚠️ Ошибка NLP-модуля: {e}. Используется локальный поиск.")

    merged = _merge_results(llm_results, db_results)
    if not merged:
        st.warning("Совпадений не найдено. Попробуйте уточнить описание или введите код вручную.")
    else:
        st.session_state.classification_results = merged
        st.session_state.api_unavailable = False
        st.session_state.calculation_done = False
        st.rerun()

if manual_mode_btn and all_filled:
    desc = (product_description or "").strip()
    db_results = find_codes_by_description(desc, top_n=3)
    st.session_state.classification_results = [dict(r, source="db") for r in db_results]
    st.session_state.api_unavailable = True
    st.session_state.calculation_done = False
    st.rerun()


# ──────────────────────────────────────────────────────────────
# Результаты классификации + выбор кода (часть блока 2)
# ──────────────────────────────────────────────────────────────
show_classification = st.session_state.classification_results is not None

if show_classification:
    st.markdown("---")
    results = st.session_state.classification_results or []

    if results:
        has_db = any(r.get("source") in ("db", "both") for r in results)
        has_llm = any(r.get("source") in ("llm", "both") for r in results)
        src_parts = []
        if has_db:
            src_parts.append("🗄️ локальная база знаний")
        if has_llm:
            src_parts.append("🧠 внешний NLP-модуль")
        st.caption(f"Источники рекомендаций: {', '.join(src_parts)}")

        cols = st.columns(min(len(results), 3))
        for i, (col, item) in enumerate(zip(cols, results[:3])):
            with col:
                code = item["code"]
                verified = verify_code(code, ref_date=ref_date)
                src = item.get("source", "llm")
                score_info = score_code_match(code, product_description or "", ref_date=ref_date)

                src_badge = {
                    "db":   "🗄️ База знаний",
                    "both": "🗄️+🧠 База + NLP",
                    "llm":  "🧠 NLP-модуль",
                }.get(src, "")

                if verified:
                    duty_info = get_duty_info(code, ref_date=ref_date)
                    if duty_info:
                        st.success(f"**{code}**\n\n{src_badge} ✅ ставки доступны")
                    else:
                        st.warning(
                            f"**{code}**\n\n{src_badge} ⚠️ код найден в ТН ВЭД, "
                            f"но ставка на {ref_date} не найдена"
                        )
                    st.write(verified["description"])
                    if duty_info:
                        _sign = duty_info.get("rate_sign", "%")
                        if _sign == "%":
                            _rate_str = f"{duty_info['duty_rate']}%"
                        elif _sign == "978":
                            _rate_str = f"{duty_info['duty_rate']} EUR/ед."
                        elif _sign == "840":
                            _rate_str = f"{duty_info['duty_rate']} USD/ед."
                        else:
                            _rate_str = f"{duty_info['duty_rate']} ₽/ед."
                        _excise_str = f", акциз: {duty_info['excise']} ₽" if duty_info.get("excise") else ""
                        st.caption(
                            f"Пошлина: {_rate_str} ({duty_info['duty_type']}), "
                            f"НДС: {duty_info['vat_rate']}%{_excise_str}"
                        )
                    if score_info["score"] > 0:
                        st.info(f"📊 {score_info['explanation']}")
                        for d in score_info["details"]:
                            st.caption(f"• {d}")
                else:
                    st.warning(f"**{code}**\n\n{src_badge} ⚠️ не найден в справочнике")
                    st.write(item["name"])

                reasoning = item.get("llm_reasoning") or item.get("reasoning", "")
                if reasoning:
                    with st.expander("Обоснование"):
                        st.write(reasoning)

    st.markdown("**Выберите код ТН ВЭД:**")

    if results:
        radio_options = []
        for item in results:
            code = item["code"]
            verified = verify_code(code, ref_date=ref_date)
            mark = "✅" if verified else "⚠️"
            name = (verified["description"] if verified else item["name"])[:60]
            src = item.get("source", "llm")
            src_label = {"db": "[БД]", "both": "[БД+NLP]", "llm": "[NLP]"}.get(src, "")
            radio_options.append(f"{code} {src_label} — {name} {mark}")
        radio_options.append("✏️ Ввести код вручную")
        selected_option = st.radio("Выберите код:", radio_options, key="code_selection")
    else:
        selected_option = "✏️ Ввести код вручную"
        st.info("Введите код ТН ВЭД вручную.")

    manual_code = ""
    if selected_option == "✏️ Ввести код вручную":
        manual_code = st.text_input(
            "Код ТН ВЭД (10 знаков):", max_chars=10,
            key="manual_code", placeholder="например: 8708301000",
        )

    if selected_option == "✏️ Ввести код вручную":
        chosen_code = manual_code.strip()
    else:
        chosen_code = selected_option.split(" ")[0].strip()

    chosen_verified = verify_code(chosen_code, ref_date=ref_date) if chosen_code else None
    chosen_duty_info = get_duty_info(chosen_code, ref_date=ref_date) if chosen_code else None
    is_unverified = bool(chosen_code) and chosen_verified is None

    if chosen_code:
        if chosen_verified:
            if chosen_duty_info:
                st.success(
                    f"✅ Код **{chosen_code}** найден, ставки доступны на {ref_date} — расчёт возможен. "
                    f"{chosen_verified['description']}"
                )
            else:
                st.warning(
                    f"⚠️ Код **{chosen_code}** найден в ТН ВЭД, но ставка на {ref_date} не найдена. "
                    f"Расчёт по справочнику невозможен — попробуйте другую дату декларирования "
                    f"или подтвердите ставку вручную."
                )
            sc = score_code_match(chosen_code, product_description or "", ref_date=ref_date)
            if sc["score"] > 0:
                st.info(f"📊 Скоринг: {sc['explanation']}")

            # ── Паспорт классификационного решения ──
            with st.expander("🪪 Паспорт классификационного решения", expanded=True):
                matched_keywords = []
                for d in sc.get("details", []):
                    matched_keywords.append(d.split(": ", 1)[-1] if ": " in d else d)
                passport_data = {
                    "Параметр": [
                        "Код ТН ВЭД",
                        "Статус",
                        "Группа",
                        "Описание",
                        "Ставка пошлины",
                        "Ставка НДС",
                        "Акциз",
                        "Источник ставки",
                        "Дата обновления записи",
                        "Скоринг признаков",
                        "Совпавшие признаки",
                    ],
                    "Значение": [
                        chosen_code,
                        "найден в локальной базе знаний",
                        str(chosen_verified.get("group_number", "")),
                        chosen_verified["description"],
                        _format_duty_rate(chosen_verified),
                        f"{chosen_verified['vat_rate']}%",
                        f"{chosen_verified.get('excise', 0)} ₽" if chosen_verified.get('excise') else "нет",
                        "CustomsReference.DB" if REF_DB_AVAILABLE else "локальная база знаний",
                        chosen_verified.get("updated_at", "—"),
                        f"{sc['score']} баллов из {sc['max_score']}",
                        "; ".join(matched_keywords) if matched_keywords else "нет совпадений",
                    ],
                }
                st.dataframe(passport_data, use_container_width=True, hide_index=True)
        else:
            st.warning(f"⚠️ Код **{chosen_code}** отсутствует в локальном справочнике.")

    manual_confirmed = False
    manual_duty_rate = 0.0
    manual_vat_rate = 22.0

    needs_manual_rates = bool(chosen_code) and chosen_duty_info is None

    if needs_manual_rates:
        manual_confirmed = st.checkbox(
            "Я проверил код/ставку самостоятельно и подтверждаю корректность",
            key="manual_confirm",
        )
        if manual_confirmed:
            c1, c2 = st.columns(2)
            with c1:
                manual_duty_rate = st.number_input(
                    "Ставка пошлины (%)", min_value=0.0, max_value=100.0,
                    value=0.0, format="%.1f", key="manual_duty",
                )
            with c2:
                manual_vat_rate = st.number_input(
                    "Ставка НДС (%)", min_value=0.0, max_value=100.0,
                    value=22.0, format="%.1f", key="manual_vat",
                )

    eur_rate = CURRENCY_RATES.get("EUR", 100.0)
    usd_rate = CURRENCY_RATES.get("USD", 92.5)
    weight_input = 0.0
    if chosen_verified and chosen_verified.get("duty_type") in ("специфическая", "комбинированная"):
        st.info("ℹ️ Специфическая/комбинированная ставка: укажите курсы валют и вес/количество.")
        c1, c2, c3 = st.columns(3)
        with c1:
            eur_default = round(get_currency_rate("EUR")["rate"], 4) if get_currency_rate("EUR") else CURRENCY_RATES.get("EUR", 100.0)
            eur_rate = st.number_input("Курс ЕВРО (₽)", min_value=0.01,
                                       value=eur_default, format="%.4f", key="eur_rate_input")
        with c2:
            usd_default = round(get_currency_rate("USD")["rate"], 4) if get_currency_rate("USD") else CURRENCY_RATES.get("USD", 92.5)
            usd_rate = st.number_input("Курс USD (₽)", min_value=0.01,
                                       value=usd_default, format="%.4f", key="usd_rate_input")
        with c3:
            weight_input = st.number_input("Вес/количество (кг/шт)",
                                           min_value=0.0, value=0.0, format="%.2f", key="weight_input")

    # ── Кнопка расчёта
    code_ok = bool(chosen_code) and len(chosen_code) >= 4
    verification_ok = (chosen_duty_info is not None) or manual_confirmed

    calc_btn = st.button(
        "💰 Рассчитать платежи",
        type="primary",
        use_container_width=True,
        disabled=not (code_ok and verification_ok),
    )

    if calc_btn and code_ok and verification_ok:
        chosen_reasoning = ""
        for item in results:
            if item.get("code") == chosen_code:
                chosen_reasoning = item.get("llm_reasoning") or item.get("reasoning", "")
                break
        chosen_score = score_code_match(chosen_code, product_description or "", ref_date=ref_date) if chosen_verified else None

        try:
            result = calculate_all_payments(
                invoice_price=invoice_price,
                delivery_cost=delivery_cost,
                insurance_cost=insurance_cost,
                exchange_rate=exchange_rate,
                hs_code=chosen_code,
                country_code=selected_country_code,
                weight=weight_input,
                eur_rate=eur_rate,
                usd_rate=usd_rate,
                allow_unverified=manual_confirmed,
                manual_duty_rate=manual_duty_rate,
                manual_vat_rate=manual_vat_rate,
                ref_date=ref_date,
            )
            st.session_state.last_calculation = result
            st.session_state.last_code = chosen_code
            st.session_state.last_description = (product_description or "").strip()
            st.session_state.last_reasoning = chosen_reasoning
            st.session_state.last_score_info = chosen_score
            st.session_state.calculation_done = True
            st.rerun()
        except UnverifiedCodeError as e:
            st.error(f"🚫 {e}")
        except Exception as e:
            st.error(f"❌ Ошибка расчёта: {e}")


# ──────────────────────────────────────────────────────────────
# БЛОКИ 3–5: Результаты расчёта
# ──────────────────────────────────────────────────────────────
if st.session_state.calculation_done and st.session_state.last_calculation:
    result = st.session_state.last_calculation
    st.markdown("---")

    # БЛОК 3: Расчёт таможенных платежей
    st.subheader("💰 3. Расчёт таможенных платежей")
    st.metric(
        label="💰 Итого таможенные платежи",
        value=f"{fmt(result['total'])} ₽",
        delta=f"{result['share_percent']}% от таможенной стоимости",
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Таможенная стоимость", f"{fmt(result['customs_value'])} ₽")
    m2.metric("Ввозная пошлина", f"{fmt(result['duty_amount'])} ₽",
              delta=f"{result['duty_rate']}% × {result['duty_coefficient']}")
    m3.metric("НДС", f"{fmt(result['vat_amount'])} ₽", delta=f"{result['vat_rate']}%")
    m4.metric("Таможенный сбор", f"{fmt(result['customs_fee'])} ₽")

    with st.expander("📑 Детализация расчёта"):
        st.dataframe({
            "Параметр": [
                "Код ТН ВЭД", "Источник ставок", "Тип пошлины",
                "Ставка пошлины (%)", "Коэффициент преференции",
                "Таможенная стоимость (₽)", "Пошлина (₽)",
                f"НДС ({result['vat_rate']}%) (₽)",
                "Таможенный сбор (₽)", "Итого (₽)", "Доля от ТС (%)",
            ],
            "Значение": [
                st.session_state.last_code, result["duty_source"], result["duty_type"],
                str(result["duty_rate"]), str(result["duty_coefficient"]),
                fmt(result["customs_value"]), fmt(result["duty_amount"]),
                fmt(result["vat_amount"]), fmt(result["customs_fee"]),
                fmt(result["total"]), str(result["share_percent"]),
            ],
        }, use_container_width=True, hide_index=True)

    # БЛОК 4: Применённые правила и контроль результата
    st.subheader("⚙️ 4. Применённые правила и контроль результата")
    applied = result.get("applied_rules", [])
    rule_ids_str = ", ".join(r["id"] for r in applied) if applied else "—"
    st.markdown(f"**Применённые продукционные правила:** {rule_ids_str}")
    for rule in applied:
        st.markdown(f"- **{rule['id']}** — {rule['name']}: {rule['explanation']}")

    code_in_db_flag = bool(verify_code(st.session_state.last_code, ref_date=ref_date))

    with st.expander("🛡️ Технический контроль результата"):
        checks = [
            ("✅" if st.session_state.classification_results else "⚠️",
             "Ответ получен от модуля поддержки классификации"),
            ("✅" if len(st.session_state.last_code) == 10 else "⚠️",
             "Код имеет корректный формат (10 знаков)"),
            ("✅" if code_in_db_flag else "❌",
             "Код проверен по локальной базе знаний"),
            ("✅" if code_in_db_flag else "❌",
             "Ставки извлечены из базы знаний"),
            ("✅", "Расчёт выполнен детерминированным модулем (экспертная подсистема)"),
            ("⚠️", "Итоговое решение требует подтверждения специалистом"),
        ]
        for icon, text in checks:
            st.markdown(f"{icon} {text}")
        st.markdown("---")
        st.markdown("**Источники расчётных данных:**")
        if REF_DB_AVAILABLE:
            st.markdown(
                "- Код ТН ВЭД → `TNVEDHead` (CustomsReference.DB, 55 459 кодов)\n"
                "- Ставка пошлины → `EntranceDuty` (262 117 записей)\n"
                "- Ставка НДС → `VAT` (55 954 записей)\n"
                "- Курсы валют ЦБ РФ → `CurrencyRates` (UserData.DB)\n"
                "- Таможенный сбор → таблица `customs_fees` (ПП РФ № 1637 ред. № 1638)\n"
                "- Расчёт платежей → продукционные правила R1–R18\n"
                "- Таможенная стоимость → метод 1, по стоимости сделки (ТК ЕАЭС, ст. 39)"
            )
        else:
            st.markdown(
                "- Код ТН ВЭД и ставка пошлины → таблица `hs_codes` (локальная)\n"
                "- Таможенный сбор → таблица `customs_fees` (ПП РФ № 1637 ред. № 1638)\n"
                "- Расчёт платежей → продукционные правила R1–R18\n"
                "- Таможенная стоимость → метод 1, по стоимости сделки (ТК ЕАЭС, ст. 39)"
            )

    # БЛОК 5: Экспертное заключение
    st.subheader("📝 5. Экспертное заключение")

    try:
        _country_name = selected_country_label.split(" (")[0]
    except Exception:
        _country_name = selected_country_code

    code_in_db = bool(verify_code(st.session_state.last_code, ref_date=ref_date))

    # Краткое заключение — 4 строки на экране
    _code_status = ("подтверждён в локальной базе знаний" if code_in_db
                    else "введён вручную, верификация не выполнена")
    with st.container(border=True):
        st.markdown(
            f"Код **{st.session_state.last_code}** — {_code_status}.  \n"
            f"Расчёт выполнен по продукционным правилам: {rule_ids_str}.  \n"
            f"Итоговые таможенные платежи: **{fmt(result['total'])} ₽**.  \n"
            f"*Результат носит рекомендательный характер и требует подтверждения специалистом.*"
        )

    # Полное заключение — только для скачивания
    score_info = st.session_state.last_score_info
    full_conclusion = generate_conclusion(
        result=result,
        hs_code=st.session_state.last_code,
        product_description=st.session_state.last_description,
        country_name=_country_name,
        country_code=selected_country_code,
        currency=currency,
        invoice_price=invoice_price,
        delivery_cost=delivery_cost,
        insurance_cost=insurance_cost,
        exchange_rate=exchange_rate,
        code_reasoning=st.session_state.last_reasoning,
        score_explanation=score_info["explanation"] if score_info else "",
        declaration_date=declaration_date,
    )

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            label="📥 Скачать заключение (.txt)",
            data=full_conclusion.encode("utf-8"),
            file_name=f"conclusion_{st.session_state.last_code}_{declaration_date}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with dl2:
        st.download_button(
            label="📊 Скачать расчёт (.csv)",
            data=result_to_csv_bytes(result, st.session_state.last_code,
                                     st.session_state.last_description,
                                     _country_name, currency),
            file_name=f"calculation_{st.session_state.last_code}_{declaration_date}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # Протокол тестирования — в раскрывающемся блоке
    with st.expander("🧪 Протокол тестирования (апробация)"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            expected_code = st.text_input("Ожидаемый код ТН ВЭД", key="expected_code")
        with c2:
            manual_time = st.number_input("Время вручную (мин)", min_value=0.0,
                                          value=15.0, key="manual_time")
        with c3:
            system_time = st.number_input("Время системы (мин)", min_value=0.0,
                                          value=1.0, key="system_time")
        with c4:
            result_comment = st.text_input("Комментарий", key="result_comment")

        if st.button("💾 Сохранить результат", use_container_width=True, key="save_test"):
            suggested = ", ".join([item.get("code", "") for item in (st.session_state.classification_results or [])])
            save_test_result({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "product_description": st.session_state.last_description,
                "expected_code": expected_code,
                "suggested_codes": suggested,
                "selected_code": st.session_state.last_code,
                "code_found_in_db": "да" if code_in_db else "нет",
                "customs_value": result["customs_value"],
                "duty": result["duty_amount"],
                "vat": result["vat_amount"],
                "fee": result["customs_fee"],
                "total_payment": result["total"],
                "manual_time_min": manual_time,
                "system_time_min": system_time,
                "result_comment": result_comment,
            })
            st.success("✅ Результат сохранён")

    st.markdown("---")
    col_add, col_new = st.columns(2)
    with col_add:
        if st.button("➕ Добавить позицию в поставку", use_container_width=True, key="add_pos"):
            desc_short = (st.session_state.last_description[:55] + "…"
                          if len(st.session_state.last_description) > 55
                          else st.session_state.last_description)
            st.session_state.positions.append({
                "description": desc_short,
                "code": st.session_state.last_code,
                "customs_value": result["customs_value"],
                "duty": result["duty_amount"],
                "vat": result["vat_amount"],
            })
            st.session_state.classification_results = None
            st.session_state.calculation_done = False
            st.rerun()
    with col_new:
        if st.button("🔄 Новый товар", use_container_width=True, key="new_prod"):
            st.session_state.classification_results = None
            st.session_state.calculation_done = False
            st.rerun()


# ──────────────────────────────────────────────────────────────
# Сводная таблица поставки
# ──────────────────────────────────────────────────────────────
if len(st.session_state.positions) >= 1:
    st.markdown("---")
    pos_word = "позиция" if len(st.session_state.positions) == 1 else "позиций"
    st.subheader(f"📦 Поставка — {len(st.session_state.positions)} {pos_word}")
    total_cv = sum(p["customs_value"] for p in st.session_state.positions)
    total_duty = sum(p["duty"] for p in st.session_state.positions)
    total_vat = sum(p["vat"] for p in st.session_state.positions)
    total_fee = get_customs_fee(total_cv)
    total_all = round(total_duty + total_vat + total_fee, 2)
    rows = [{"№": i, "Товар": p["description"], "Код": p["code"],
             "ТС (₽)": fmt(p["customs_value"]), "Пошлина (₽)": fmt(p["duty"]),
             "НДС (₽)": fmt(p["vat"])}
            for i, p in enumerate(st.session_state.positions, 1)]
    rows.append({"№": "", "Товар": "ИТОГО", "Код": "",
                 "ТС (₽)": fmt(total_cv), "Пошлина (₽)": fmt(total_duty), "НДС (₽)": fmt(total_vat)})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.info(f"🏛️ Таможенный сбор (совокупная ТС {fmt(total_cv)} ₽): **{fmt(total_fee)} ₽**")
    st.metric("Совокупный платёж по поставке", f"{fmt(total_all)} ₽")
    if st.button("🗑️ Очистить поставку", key="clear"):
        st.session_state.positions = []
        st.rerun()


# ──────────────────────────────────────────────────────────────
# Дисклеймер
# ──────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Результат расчёта носит рекомендательный характер и предназначен для предварительной "
    "оценки импортной поставки. Окончательное решение о классификации товара по ТН ВЭД "
    "принимает специалист. Ответственность за декларирование и уплату платежей лежит "
    "на декларанте (ТК ЕАЭС, ст. 84; НК РФ, ст. 174)."
)
