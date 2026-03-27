#!/usr/bin/env python3
"""
Генерация синтетических BSL файлов разных размеров для бенчмарков.

Каждый файл содержит реалистичные паттерны:
- Процедуры с Перем (включая неиспользуемые — активирует BSL007)
- Знач-параметры (активирует BSL021)
- Регионы с содержимым
- Циклы, условия, вложенность

Использование:
    python scripts/bench_generate_fixtures.py
    # Создаёт tests/fixtures/bench_100.bsl, bench_500.bsl, и т.д.
"""
from __future__ import annotations

from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

SIZES = [100, 500, 1000, 3000, 5000]

_VAR_NAMES = [
    "ТекущаяСтрока",
    "ИндексЭлемента",
    "КоличествоСтрок",
    "РезультатПоиска",
    "МассивДанных",
    "СтруктураРезультата",
    "ВременнаяПеременная",
    "ФлагОшибки",
    "СчётчикЦикла",
    "ИтоговаяСумма",
    "НачальноеЗначение",
    "КонечноеЗначение",
    "ТекущийЭлемент",
    "СписокОшибок",
    "ПараметрЗапроса",
]

_PROC_NAMES = [
    "ОбработатьСтроку",
    "ВычислитьСумму",
    "ПроверитьДанные",
    "ЗаписатьВЖурнал",
    "ИнициализироватьМодуль",
    "ОчиститьБуфер",
    "ВыполнитьЗапрос",
    "СохранитьДанные",
    "ЗагрузитьКонфигурацию",
    "ПроверитьПрава",
    "ОбновитьКэш",
    "ОтправитьУведомление",
]

_REGION_NAMES = [
    "ОбщиеПеременные",
    "СлужебныеПроцедуры",
    "ПубличныеМетоды",
    "ВнутренниеФункции",
    "ОбработчикиСобытий",
    "ВспомогательныеФункции",
]


def _make_proc(proc_idx: int, n_vars: int = 4, n_body_lines: int = 25) -> list[str]:
    """Генерирует одну процедуру с объявлениями переменных и телом."""
    name = _PROC_NAMES[proc_idx % len(_PROC_NAMES)] + str(proc_idx)
    # Знач-параметр активирует BSL021
    lines = [f"Процедура {name}(Параметр1, Знач ПараметрЗнач = Неопределено)"]

    # Неиспользуемая переменная — активирует BSL007
    unused = f"НеиспользуемаяПерем{proc_idx}"
    lines.append(f"\tПерем {unused};")

    # Используемые переменные
    used_vars = [_VAR_NAMES[i % len(_VAR_NAMES)] + str(proc_idx) for i in range(min(n_vars, 3))]
    for v in used_vars:
        lines.append(f"\tПерем {v};")

    lines.append("")

    # Инициализация переменных
    for i, v in enumerate(used_vars):
        lines.append(f"\t{v} = {i};")

    lines.append("")
    lines.append("\tЕсли Параметр1 = Неопределено Тогда")
    lines.append("\t\tВозврат;")
    lines.append("\tКонецЕсли;")
    lines.append("")

    # Цикл
    lines.append("\tДля Индекс = 1 По 10 Цикл")
    if used_vars:
        lines.append(f"\t\t{used_vars[0]} = {used_vars[0]} + Индекс;")
        lines.append(f"\t\tЕсли {used_vars[0]} > 50 Тогда")
        if len(used_vars) > 1:
            lines.append(f"\t\t\t{used_vars[1]} = {used_vars[0]};")
        lines.append("\t\tКонецЕсли;")
    lines.append("\tКонецЦикла;")
    lines.append("")

    # Дополнительные строки до нужного размера
    current = len(lines)
    extra = max(0, n_body_lines - current)
    for i in range(extra):
        v = used_vars[i % len(used_vars)] if used_vars else "Индекс"
        lines.append(f"\t{v} = {v} + {i % 10};")

    lines.append("")
    lines.append("КонецПроцедуры")
    lines.append("")
    return lines


def generate_bsl(target_lines: int) -> str:
    """Генерирует BSL-файл с ~target_lines строками."""
    out: list[str] = [
        "// Синтетический BSL файл для бенчмарков производительности",
        f"// Целевой размер: {target_lines} строк",
        "// Содержит: процедуры, Перем-объявления, циклы, условия, регионы",
        "",
    ]

    # ~30 строк на процедуру, 4 процедуры на регион, ~6 строк на регион-обёртку
    lines_per_proc = 30
    procs_per_region = 4
    lines_per_region = procs_per_region * lines_per_proc + 6
    n_regions = max(1, target_lines // lines_per_region)

    proc_idx = 0
    for r_idx in range(n_regions):
        region_name = _REGION_NAMES[r_idx % len(_REGION_NAMES)] + str(r_idx + 1)
        out.append(f"#Область {region_name}")
        out.append("")
        for _ in range(procs_per_region):
            out.extend(_make_proc(proc_idx, n_vars=4, n_body_lines=lines_per_proc))
            proc_idx += 1
        out.append("#КонецОбласти")
        out.append("")

        if len(out) >= target_lines:
            break

    return "\n".join(out)


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        content = generate_bsl(size)
        actual = len(content.splitlines())
        out_path = FIXTURE_DIR / f"bench_{size}.bsl"
        out_path.write_text(content, encoding="utf-8")
        print(f"  {out_path.name}: {actual} lines")


if __name__ == "__main__":
    print(f"Generating benchmark fixtures → {FIXTURE_DIR}")
    main()
    print("Done.")
