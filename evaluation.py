# evaluation.py — Расчёт метрик тестирования экспертной системы
#
# Читает test_results.csv и вычисляет показатели для главы 3.1 и 3.3 ВКР:
#   - количество тестов
#   - top-3 accuracy (предложенный код совпал с ожидаемым)
#   - доля кодов, найденных в БД
#   - среднее ручное время обработки
#   - среднее время обработки системой
#   - экономия времени на позицию

import csv
import os
from typing import Dict, List, Optional

from config import BASE_DIR

TEST_RESULTS_PATH = os.path.join(BASE_DIR, "test_results.csv")


def load_test_results() -> List[Dict]:
    """Загружает результаты тестирования из CSV."""
    if not os.path.exists(TEST_RESULTS_PATH):
        return []
    rows = []
    with open(TEST_RESULTS_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append(row)
    return rows


def calculate_metrics(rows: Optional[List[Dict]] = None) -> Dict:
    """
    Вычисляет метрики тестирования.

    Возвращает словарь:
      total_tests, top3_correct, top3_accuracy,
      codes_found_in_db, db_coverage,
      avg_manual_time, avg_system_time, time_saved
    """
    if rows is None:
        rows = load_test_results()

    if not rows:
        return {
            "total_tests": 0,
            "top3_correct": 0,
            "top3_accuracy": 0.0,
            "codes_found_in_db": 0,
            "db_coverage": 0.0,
            "avg_manual_time": 0.0,
            "avg_system_time": 0.0,
            "time_saved": 0.0,
        }

    total = len(rows)
    top3_correct = 0
    codes_in_db = 0
    manual_times = []
    system_times = []

    for row in rows:
        expected = (row.get("expected_code") or "").strip()
        suggested = (row.get("suggested_codes") or "").strip()
        selected = (row.get("selected_code") or "").strip()

        if expected:
            suggested_list = [c.strip() for c in suggested.split(",")]
            if expected in suggested_list or expected == selected:
                top3_correct += 1

        found = (row.get("code_found_in_db") or "").strip().lower()
        if found == "да":
            codes_in_db += 1

        try:
            mt = float(row.get("manual_time_min", 0))
            if mt > 0:
                manual_times.append(mt)
        except (ValueError, TypeError):
            pass

        try:
            st = float(row.get("system_time_min", 0))
            if st > 0:
                system_times.append(st)
        except (ValueError, TypeError):
            pass

    tests_with_expected = sum(1 for r in rows if (r.get("expected_code") or "").strip())
    top3_accuracy = round(top3_correct / tests_with_expected * 100, 1) if tests_with_expected > 0 else 0.0

    db_coverage = round(codes_in_db / total * 100, 1) if total > 0 else 0.0
    avg_manual = round(sum(manual_times) / len(manual_times), 1) if manual_times else 0.0
    avg_system = round(sum(system_times) / len(system_times), 1) if system_times else 0.0
    saved = round(avg_manual - avg_system, 1)

    return {
        "total_tests": total,
        "top3_correct": top3_correct,
        "top3_accuracy": top3_accuracy,
        "codes_found_in_db": codes_in_db,
        "db_coverage": db_coverage,
        "avg_manual_time": avg_manual,
        "avg_system_time": avg_system,
        "time_saved": saved,
    }


if __name__ == "__main__":
    m = calculate_metrics()
    if m["total_tests"] == 0:
        print("Файл test_results.csv пуст или отсутствует.")
    else:
        print(f"Количество тестов:           {m['total_tests']}")
        print(f"Top-3 accuracy:              {m['top3_accuracy']}% ({m['top3_correct']} из {m['total_tests']})")
        print(f"Код найден в БД:             {m['codes_found_in_db']} ({m['db_coverage']}%)")
        print(f"Среднее ручное время:        {m['avg_manual_time']} мин")
        print(f"Среднее время в системе:     {m['avg_system_time']} мин")
        print(f"Экономия на позицию:         {m['time_saved']} мин")
