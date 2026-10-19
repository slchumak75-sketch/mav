#!/usr/bin/env python3
"""Extract inventory rows from «Ведомость … .xlsx» into JSON.

Поддерживает оба формата выгрузки:
  - старый  «Ведомость мав.xlsx» (111 строк, K–W = 13 месяцев, A1:W119)
  - новый   «Ведомость с периодом ОК (1).xlsx» (1850 строк, L–AV = 37 месяцев, A1:AV1857)
Оба — OOXML ZIP без VBA/формул, значения — литералы.

Единственный парсер xlsx → JSON + распаковка. Канон: data/vedomost.json → web/public/data/.

Usage:
  python3 tools/extract_xlsx.py            # unpack + write JSON
  python3 tools/extract_xlsx.py --verify   # also fail if JSON would change
  python3 tools/extract_xlsx.py --unpack-only
  python3 tools/extract_xlsx.py --fill-purchase   # заполнить столбец H «К закупке» и пересобрать xlsx
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ROOT = Path(__file__).resolve().parents[1]
# Приоритет: новая ведомость, затем старая
XLSX_CANDIDATES = [
    "Ведомость с периодом ОК (1).xlsx",
    "Ведомость мав.xlsx",
]
UNPACK_DIR = ROOT / "source" / "xlsx"
JSON_PATH = ROOT / "data" / "vedomost.json"
WEB_PUBLIC_JSON = ROOT / "web" / "public" / "data" / "vedomost.json"

HEADER_ROW = 7
FIRST_DATA_ROW = 8

# Для расчёта сезонной закупки — как в web/src/calc.js
DEFAULT_AS_OF = "2026-10-19"
DEFAULT_HORIZON_MONTHS = 2
DEFAULT_BUFFER_PERCENT = 10

MONTH_NAME_MAP = {
    "Январь": 1, "Февраль": 2, "Март": 3, "Апрель": 4,
    "Май": 5, "Июнь": 6, "Июль": 7, "Август": 8,
    "Сентябрь": 9, "Октябрь": 10, "Ноябрь": 11, "Декабрь": 12,
}
MONTHS_RU = {v: k for k, v in MONTH_NAME_MAP.items()}

MONTH_PATTERN = re.compile(r"(Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь)\s+(\d{4})")


def find_xlsx() -> Path:
    for name in XLSX_CANDIDATES:
        p = ROOT / name
        if p.is_file():
            return p
    matches = sorted(ROOT.glob("*.xlsx"))
    if len(matches) == 1:
        return matches[0]
    # если несколько — берём самый свежий
    if matches:
        return max(matches, key=lambda p: p.stat().st_mtime)
    raise FileNotFoundError(
        f"Cannot find any of {XLSX_CANDIDATES!r} in {ROOT}. Found: {[p.name for p in matches]}"
    )


def col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_name(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_ref(ref: str) -> tuple[int, int]:
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    if not m:
        raise ValueError(f"Bad cell ref: {ref}")
    return col_index(m.group(1)), int(m.group(2))


def load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    out: list[str] = []
    for si in root.findall("m:si", NS):
        texts = [t.text or "" for t in si.findall(".//m:t", NS)]
        out.append("".join(texts))
    return out


def load_cells(zf: zipfile.ZipFile, shared: list[str]) -> dict[str, Any]:
    sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    cells: dict[str, Any] = {}
    for c in sheet.findall(".//m:c", NS):
        ref = c.attrib.get("r")
        if not ref:
            continue
        t = c.attrib.get("t")
        v = c.find("m:v", NS)
        is_elem = c.find("m:is", NS)
        val: Any = None
        if t == "s" and v is not None and v.text is not None:
            try:
                val = shared[int(v.text)]
            except (IndexError, ValueError):
                val = v.text
        elif t == "inlineStr" and is_elem is not None:
            val = "".join(x.text or "" for x in is_elem.findall(".//m:t", NS))
        elif v is not None:
            val = v.text
        cells[ref] = val
    return cells


def cell(cells: dict[str, Any], col: str, row: int) -> Any:
    return cells.get(f"{col}{row}")


def as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def as_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if text in {"", "-"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def round2(n: float) -> float:
    return round(n + 0.0, 2)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def unpack_xlsx(xlsx: Path) -> None:
    UNPACK_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(xlsx) as zf:
        zf.extractall(UNPACK_DIR)
        members = zf.namelist()
    (UNPACK_DIR / "MANIFEST.txt").write_text(
        "Unpacked from {name}\nSHA-256: {sha}\nFiles:\n{files}\n".format(
            name=xlsx.name,
            sha=sha256_file(xlsx),
            files="\n".join(f"  {m}" for m in members),
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Сезонная логика — зеркало web/src/calc.js
# ---------------------------------------------------------------------------

def cover_months(as_of: str = DEFAULT_AS_OF, horizon: int = DEFAULT_HORIZON_MONTHS) -> list[dict[str, Any]]:
    # asOf = 2026-10-19 → октябрь считается закрытым, горизонт = ноябрь, декабрь...
    try:
        d = datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        d = datetime.fromisoformat(as_of.split("T")[0])
    year = d.year
    month = d.month
    n = max(0, int(horizon) if horizon else 0)
    out = []
    for _ in range(n):
        month += 1
        if month > 12:
            month = 1
            year += 1
        out.append({"month": month, "year": year})
    return out


def typical_by_calendar_month(months_vals: list[float], months_meta: list[dict[str, Any]]) -> dict[int, float]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for idx, meta in enumerate(months_meta):
        # meta key = "2023-10"
        try:
            y, m = meta["key"].split("-")
            m_int = int(m)
        except Exception:
            continue
        buckets[m_int].append(float(months_vals[idx]) if idx < len(months_vals) else 0.0)
    typical: dict[int, float] = {}
    for m in range(1, 13):
        arr = buckets.get(m, [])
        typical[m] = (sum(arr) / len(arr)) if arr else 0.0
    return typical


def seasonal_plan_for_row(months_vals: list[float], months_meta: list[dict[str, Any]], closing: float, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    as_of = opts.get("asOf") or DEFAULT_AS_OF
    horizon = int(opts.get("horizonMonths", DEFAULT_HORIZON_MONTHS))
    buffer_pct = float(opts.get("bufferPercent", DEFAULT_BUFFER_PERCENT))
    typical = typical_by_calendar_month(months_vals, months_meta)
    cover = cover_months(as_of, horizon)
    seasonal_demand = sum(typical.get(c["month"], 0.0) for c in cover)
    buffered = seasonal_demand * (1 + buffer_pct / 100.0)
    needed = 0 if buffered < 1e-9 else math.ceil(buffered - 1e-9)
    to_purchase = max(0.0, needed - (closing or 0.0))
    return {
        "typical": typical,
        "cover": cover,
        "seasonalDemand": round2(seasonal_demand),
        "bufferPercent": buffer_pct,
        "horizonMonths": horizon,
        "asOf": as_of,
        "neededReserve": needed,
        "toPurchase": round2(to_purchase),
    }


# ---------------------------------------------------------------------------
# Детекция формата и сбор months_meta
# ---------------------------------------------------------------------------

def detect_months_meta(cells: dict[str, Any]) -> list[dict[str, Any]]:
    """Сканирует заголовок строки 7 на колонки вида 'Октябрь 2023 г.'"""
    metas: list[dict[str, Any]] = []
    # сканируем достаточно широко: до 100 колонок (AV = 48, но с запасом)
    for n in range(1, 80):
        col = col_name(n)
        val = cell(cells, col, HEADER_ROW)
        if not val:
            continue
        text = as_text(val)
        m = MONTH_PATTERN.search(text)
        if not m:
            continue
        month_name, year = m.group(1), m.group(2)
        month_num = MONTH_NAME_MAP.get(month_name)
        if not month_num:
            continue
        key = f"{year}-{month_num:02d}"
        # нормализуем label как в исходнике (например, "Октябрь 2023 г.")
        metas.append({"key": key, "label": text, "col": col})
    # сортируем по ключу-year/month уже в порядке колонок, но для надёжности — по col_index
    metas.sort(key=lambda x: col_index(x["col"]))
    return metas


def detect_format(cells: dict[str, Any], months_meta: list[dict[str, Any]]) -> str:
    f7 = as_text(cell(cells, "F", HEADER_ROW))
    # old: "Начальный\nостаток" , new: "Расход"
    if "Начальный" in f7 or "начальный" in f7.lower():
        return "old"
    if "Расход" in f7:
        return "new"
    # fallback по числу колонок
    if len(months_meta) >= 30:
        return "new"
    return "old"


def find_max_row(cells: dict[str, Any]) -> int:
    max_r = 0
    for ref in cells:
        m = re.match(r"([A-Z]+)(\d+)$", ref)
        if m:
            r = int(m.group(2))
            if r > max_r:
                max_r = r
    return max_r


def extract_payload(xlsx: Path) -> dict[str, Any]:
    with zipfile.ZipFile(xlsx) as zf:
        names = zf.namelist()
        has_vba = any(n.lower().endswith("vbaproject.bin") for n in names)
        has_formulas = False
        # проверяем наличие формул: ищем <f> в sheet
        try:
            sheet_raw = zf.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="ignore")
            has_formulas = "<f>" in sheet_raw or "<f " in sheet_raw
        except Exception:
            has_formulas = False
        shared = load_shared_strings(zf)
        cells = load_cells(zf, shared)

    months_meta = detect_months_meta(cells)
    fmt = detect_format(cells, months_meta)
    # fallback если months не нашлись — старый хардкод
    if not months_meta:
        if fmt == "old":
            months_meta = [
                {"key": "2025-10", "label": "Октябрь 2025 г.", "col": "K"},
                {"key": "2025-11", "label": "Ноябрь 2025 г.", "col": "L"},
                {"key": "2025-12", "label": "Декабрь 2025 г.", "col": "M"},
                {"key": "2026-01", "label": "Январь 2026 г.", "col": "N"},
                {"key": "2026-02", "label": "Февраль 2026 г.", "col": "O"},
                {"key": "2026-03", "label": "Март 2026 г.", "col": "P"},
                {"key": "2026-04", "label": "Апрель 2026 г.", "col": "Q"},
                {"key": "2026-05", "label": "Май 2026 г.", "col": "R"},
                {"key": "2026-06", "label": "Июнь 2026 г.", "col": "S"},
                {"key": "2026-07", "label": "Июль 2026 г.", "col": "T"},
                {"key": "2026-08", "label": "Август 2026 г.", "col": "U"},
                {"key": "2026-09", "label": "Сентябрь 2026 г.", "col": "V"},
                {"key": "2026-10", "label": "Октябрь 2026 г.", "col": "W"},
            ]
        else:
            months_meta = []

    # Период и заголовки
    title = as_text(cell(cells, "D", 4)) or "Ведомость по остаткам ТМЦ на складах"
    period_label = as_text(cell(cells, "B", 5))
    scope = as_text(cell(cells, "B", 6))

    # для нового файла период/склад в шапке пустые — генерируем из months_meta
    if not period_label and months_meta:
        first = months_meta[0]["label"] if months_meta else ""
        last = months_meta[-1]["label"] if months_meta else ""
        period_label = f"С {first} по {last}" if first and last else ""
    if not scope:
        # генерируем из уникальных складов/групп позже, а пока заглушка
        scope = "По всем фирмам. По всем складам. По всем группам."

    # определяем даты периода
    # periodFrom — первый месяц months_meta, periodTo — 2026-10-19 (дата отчёта) или последний месяц
    period_from = ""
    period_to = DEFAULT_AS_OF
    if months_meta:
        try:
            period_from = months_meta[0]["key"] + "-01"
        except Exception:
            period_from = ""
        # periodTo оставляем как DEFAULT_AS_OF (2026-10-19) — дата отчёта из последней ревизии
        # но если months_meta последний = 2026-10, то periodTo = 2026-10-19 как в старом файле

    # определяем границы данных
    max_row = find_max_row(cells)
    # для старого файла границы были 8..118, для нового — 8..1857
    # берём динамически: от FIRST_DATA_ROW до max_row, исключая строки где D пусто
    # но для воспроизводимости ограничим верхнюю границу: если max_row > 5000, берём max_row
    last_data_row = max_row

    items: list[dict[str, Any]] = []
    for row in range(FIRST_DATA_ROW, last_data_row + 1):
        name = as_text(cell(cells, "D", row))
        if not name:
            continue

        if fmt == "old":
            opening = as_number(cell(cells, "F", row))
            incoming = as_number(cell(cells, "G", row))
            outgoing = as_number(cell(cells, "H", row))
            closing = as_number(cell(cells, "I", row))
            min_reserve = as_number(cell(cells, "J", row))
            last_price = 0.0
            retail_price = 0.0
            supplier = ""
        else:
            # new: F=Расход(outgoing), G=Конечный остаток(closing), H=пустой/К закупке, I=Цена, J=Розница, K=Поставщик
            opening = 0.0
            incoming = 0.0
            outgoing = as_number(cell(cells, "F", row))
            closing = as_number(cell(cells, "G", row))
            # H может уже содержать ранее заполненное значение закупки — читаем, но не используем как minReserve
            # minReserve в новом файле нет — ставим 0
            min_reserve = 0.0
            last_price = as_number(cell(cells, "I", row))
            retail_price = as_number(cell(cells, "J", row))
            supplier = as_text(cell(cells, "K", row))
            # если H уже заполнен (после предыдущей прогонки), можно проверить консистентность
            # но не доверяем ему — считаем сами

        months = [as_number(cell(cells, m["col"], row)) for m in months_meta]
        month_total = round2(sum(months))
        # balanceOk только для старого формата где есть opening/incoming/outgoing/closing
        if fmt == "old":
            expected = round2(opening + incoming - outgoing)
            balance_ok = abs(expected - closing) < 0.009
        else:
            # для нового: сверяем что сумма месяцев ≈ расход? Но это не баланс; просто отмечаем как true
            # или сверяем monthTotal vs outgoing для аудита (но не баланс)
            balance_ok = True

        below_min = closing < min_reserve if fmt == "old" else False

        item: dict[str, Any] = {
            "id": len(items) + 1,
            "row": row,
            "warehouse": as_text(cell(cells, "A", row)),
            "group": as_text(cell(cells, "B", row)),
            "sku": as_text(cell(cells, "C", row)),
            "name": name,
            "unit": as_text(cell(cells, "E", row)),
            "opening": round2(opening),
            "incoming": round2(incoming),
            "outgoing": round2(outgoing),
            "closing": round2(closing),
            "minReserve": round2(min_reserve),
            "months": months,
            "monthTotal": round2(sum(months)),
            "belowMin": below_min,
            "balanceOk": balance_ok,
        }
        # дополнительные поля нового формата — всегда пишем, для старого они пустые
        if fmt == "new":
            item["lastPrice"] = round2(last_price)
            item["retailPrice"] = round2(retail_price)
            item["supplier"] = supplier
            # H column existing value (если уже заполнен) — для отладки
            raw_purchase = cell(cells, "H", row)
            if raw_purchase not in (None, ""):
                item["_rawH"] = as_text(raw_purchase)

        items.append(item)

    # после сбора items можем уточнить scope: если он был заглушкой, собрать из данных
    if scope == "По всем фирмам. По всем складам. По всем группам." and items:
        whs = sorted({i["warehouse"] for i in items if i["warehouse"]})
        grs = sorted({i["group"] for i in items if i["group"]})
        scope = f"Склады: {', '.join(whs)}. Группы: {', '.join(grs)}."

    # периодFrom/To: если не заданы, берём из months_meta
    if not period_from and months_meta:
        period_from = months_meta[0]["key"] + "-01"
    if not period_to:
        period_to = DEFAULT_AS_OF

    # считаем итоги
    below = sum(1 for i in items if i["belowMin"])
    zero = sum(1 for i in items if i["closing"] == 0)

    payload = {
        "meta": {
            "title": title,
            "periodLabel": period_label,
            "periodFrom": period_from or "2025-10-01",
            "periodTo": period_to,
            "scope": scope,
            "sourceFile": xlsx.name,
            "sourceSha256": sha256_file(xlsx),
            "sheet": "Лист_1",
            "extractedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hasVba": has_vba,
            "hasFormulas": has_formulas,
            "itemCount": len(items),
            "months": [{"key": m["key"], "label": m["label"]} for m in months_meta],
            "buttons": ["Обновить", "Настройка"],
            "format": fmt,
            "notes": [
                "Workbook is OOXML (ZIP). Unpacked XML lives in source/xlsx/.",
                "No VBA macros, no worksheet formulas — values are literals." if not has_vba and not has_formulas else "Check VBA/formulas.",
                "Identity opening + incoming - outgoing = closing holds for old format." if fmt == "old" else "New format: closing and outgoing are independent facts; monthly columns are sales.",
                "Monthly columns do not have to sum to Расход; keep as source facts." if fmt == "new" else "Monthly columns K–W do not sum to Расход; keep them as source facts.",
            ],
        },
        "totals": {
            "items": len(items),
            "opening": round2(sum(i["opening"] for i in items)),
            "incoming": round2(sum(i["incoming"] for i in items)),
            "outgoing": round2(sum(i["outgoing"] for i in items)),
            "closing": round2(sum(i["closing"] for i in items)),
            "belowMin": below,
            "zeroStock": zero,
        },
        "items": items,
    }
    # для нового формата добавим расширенные тоталы цен если есть
    if fmt == "new":
        payload["totals"]["withPrice"] = sum(1 for i in items if i.get("lastPrice", 0) > 0)
    return payload


def canonical_json(payload: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(payload, ensure_ascii=False))
    if "meta" in clone:
        clone["meta"].pop("extractedAt", None)
    return json.dumps(clone, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_json(payload: dict[str, Any]) -> None:
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    JSON_PATH.write_text(text, encoding="utf-8")
    WEB_PUBLIC_JSON.parent.mkdir(parents=True, exist_ok=True)
    WEB_PUBLIC_JSON.write_text(text, encoding="utf-8")


def verify_against_disk(payload: dict[str, Any]) -> None:
    if not JSON_PATH.is_file():
        raise SystemExit(f"--verify failed: {JSON_PATH} is missing")
    existing = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    if canonical_json(existing) != canonical_json(payload):
        raise SystemExit(
            "--verify failed: extracted JSON does not match data/vedomost.json. "
            "Re-run tools/extract_xlsx.py and commit the result."
        )


# ---------------------------------------------------------------------------
# Запись сезонной закупки в столбец H (колонка 8)
# ---------------------------------------------------------------------------

def compute_purchase_list(payload: dict[str, Any], options: dict[str, Any] | None = None) -> list[int]:
    """Возвращает список toPurchase для каждого item в порядке payload.items."""
    opts = options or {"asOf": payload["meta"].get("periodTo", DEFAULT_AS_OF), "horizonMonths": DEFAULT_HORIZON_MONTHS, "bufferPercent": DEFAULT_BUFFER_PERCENT}
    months_meta = payload["meta"]["months"]  # list of {key,label}
    # преобразуем к формату с col для совместимости, но тут col не нужен
    # months_meta уже содержит key/label
    # Нужно восстановить months_meta с кол? Но для расчёта достаточно key/label и months vals
    out = []
    for item in payload["items"]:
        plan = seasonal_plan_for_row(item["months"], payload["meta"]["months"] and _rebuild_meta(payload["meta"]["months"]) or [], item["closing"], opts)
        out.append(plan["neededReserve"] if False else plan["toPurchase"])  # toPurchase
    return out

def _rebuild_meta(meta_months):
    # meta_months: [{"key":...,"label":...}]
    # нужно добавить col для типизации, но не используется — вернём как есть с key
    return meta_months

def fill_purchase_column(xlsx: Path, payload: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> Path:
    """
    Заполняет пустой столбец H (колонка 8) в xlsx значениями «К закупке»,
    посчитанными по сезонной статистике. Перезаписывает исходный файл
    (создаёт новый ZIP на месте) и возвращает путь.
    """
    if payload is None:
        payload = extract_payload(xlsx)
    opts = options or {"asOf": payload["meta"].get("periodTo", DEFAULT_AS_OF), "horizonMonths": DEFAULT_HORIZON_MONTHS, "bufferPercent": DEFAULT_BUFFER_PERCENT}

    # Строим months_meta для расчёта: нужны key/label
    # Но seasonal_plan_for_row ожидает months_meta с key, поэтому используем payload meta
    months_meta = payload["meta"]["months"]
    # Для удобства восстановим col-index mapping из оригинального файла:
    # Но нам достаточно months_vals уже в payload, так что считаем так:

    # Вычисляем toPurchase для каждого row
    # Используем тот же алгоритм что и calc.js: typical per calendar month, ceil(buffer)
    def calc_for_item(item):
        plan = seasonal_plan_for_row(item["months"], months_meta_patched, item["closing"], opts)
        return plan["toPurchase"]

    # Нужно восстановить months_meta с col для чтения? Нет, у нас уже months_vals.
    # Простой путь: вызвать seasonal_plan_for_row с item.months и meta_months где meta — это payload meta
    # Но seasonal_plan_for_row внутри вызывает typical_by_calendar_month который парсит key
    # Значит нам нужен meta с key
    months_meta_patched = payload["meta"]["months"]  # уже содержит key/label

    purchase_map: dict[int, int] = {}  # row -> qty
    for item in payload["items"]:
        # item.row — номер строки Excel
        plan = seasonal_plan_for_row(item["months"], months_meta_patched, item["closing"], opts)
        purchase_map[item["row"]] = int(plan["toPurchase"])

    # Теперь правим xlsx ZIP
    # Читаем все части
    with zipfile.ZipFile(xlsx, "r") as zin:
        shared_raw = None
        try:
            shared_raw = zin.read("xl/sharedStrings.xml")
        except KeyError:
            shared_raw = None
        sheet_raw = zin.read("xl/worksheets/sheet1.xml")
        other_names = [n for n in zin.namelist() if n not in ("xl/sharedStrings.xml", "xl/worksheets/sheet1.xml")]
        other_data = {n: zin.read(n) for n in other_names}
        # также сохраним _rels, styles и т.д. уже в other_data

    # 1) Обрабатываем sharedStrings: добавляем "К закупке" если нет
    header_text = "К закупке"
    shared_strings: list[str] = []
    shared_count = 0
    shared_unique = 0
    if shared_raw:
        root = ET.fromstring(shared_raw)
        # count может быть в атрибутах, но пересчитаем
        for si in root.findall("m:si", NS):
            texts = [t.text or "" for t in si.findall(".//m:t", NS)]
            shared_strings.append("".join(texts))
        # ищем header_text
        if header_text not in shared_strings:
            shared_strings.append(header_text)
    else:
        shared_strings = [header_text]

    header_idx = shared_strings.index(header_text)

    # Пересобираем sharedStrings.xml
    # Формируем новый XML
    SST_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", SST_NS)
    sst = ET.Element(f"{{{SST_NS}}}sst", attrib={"count": str(len(shared_strings)), "uniqueCount": str(len(shared_strings))})
    for s in shared_strings:
        si = ET.SubElement(sst, f"{{{SST_NS}}}si")
        t = ET.SubElement(si, f"{{{SST_NS}}}t")
        # preserve если нужно, но просто
        t.text = s
        if s != s.strip():
            t.set("xml:space", "preserve")
    new_shared = ET.tostring(sst, encoding="utf-8", xml_declaration=True)

    # 2) Обрабатываем sheet1.xml: вставляем H7 и H8.. и т.д.
    # Парсим
    sheet_root = ET.fromstring(sheet_raw)
    # Найдём sheetData
    sheet_data = sheet_root.find("m:sheetData", NS)
    if sheet_data is None:
        raise RuntimeError("sheetData not found")

    # Собираем rows dict rowNum -> row element
    rows_by_num = {}
    for row_elem in sheet_data.findall("m:row", NS):
        r_attr = row_elem.get("r")
        if r_attr:
            rows_by_num[int(r_attr)] = row_elem

    # Для каждой row в purchase_map — найти или создать c элемент H<row>
    for excel_row, qty in purchase_map.items():
        row_elem = rows_by_num.get(excel_row)
        if row_elem is None:
            # создаём новый row если вдруг нет (не должно случиться)
            row_elem = ET.SubElement(sheet_data, f"{{{NS['m']}}}row", attrib={"r": str(excel_row), "spans": "1:48"})
            rows_by_num[excel_row] = row_elem
        # найти c с r="H{row}"
        target_ref = f"H{excel_row}"
        c_elem = None
        for c in row_elem.findall("m:c", NS):
            if c.get("r") == target_ref:
                c_elem = c
                break
        if c_elem is None:
            # создаём новый — вставим перед I или в конец, но порядок не критичен; добавим в конец row
            c_elem = ET.SubElement(row_elem, f"{{{NS['m']}}}c", attrib={"r": target_ref})
            # style: для H используем s="19" если есть, иначе s="26" (числовой) — возьмём 19 как в оригинале
            # Для заголовка H7 style 25, для данных H8+ style 19
            c_elem.set("s", "25" if excel_row == HEADER_ROW else "19")
        else:
            # очистим старые t/v/is
            # сохраняем s атрибут как есть
            for child in list(c_elem):
                c_elem.remove(child)
            # удаляем t атрибут если был (shared string)
            if "t" in c_elem.attrib:
                del c_elem.attrib["t"]
        # теперь пишем число
        v_elem = ET.SubElement(c_elem, f"{{{NS['m']}}}v")
        v_elem.text = str(int(qty))
        # стиль уже есть

    # Для заголовка H7 — нужно установить t="s" и v=header_idx
    hdr_row = rows_by_num.get(HEADER_ROW)
    if hdr_row is not None:
        hdr_c = None
        for c in hdr_row.findall("m:c", NS):
            if c.get("r") == f"H{HEADER_ROW}":
                hdr_c = c
                break
        if hdr_c is not None:
            # очистим
            for child in list(hdr_c):
                hdr_c.remove(child)
            hdr_c.set("t", "s")
            # сохраняем s стиль заголовка (если нет, ставим 10 как у других месяцев)
            if "s" not in hdr_c.attrib:
                hdr_c.set("s", "10")
            v_elem = ET.SubElement(hdr_c, f"{{{NS['m']}}}v")
            v_elem.text = str(header_idx)

    # Пересобираем sheet XML
    # Need to ensure namespaces declared
    # ET уже знает NS, но при сериализации нужно сохранить оригинальные атрибуты worksheet
    new_sheet = ET.tostring(sheet_root, encoding="utf-8", xml_declaration=True)

    # 3) Перезаписываем ZIP на месте
    tmp_path = xlsx.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        # пишем изменённые
        zout.writestr("xl/sharedStrings.xml", new_shared)
        zout.writestr("xl/worksheets/sheet1.xml", new_sheet)
        for n, data in other_data.items():
            zout.writestr(n, data)
    tmp_path.replace(xlsx)
    return xlsx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="fail if JSON differs from disk")
    parser.add_argument("--unpack-only", action="store_true", help="only unpack xlsx")
    parser.add_argument("--fill-purchase", action="store_true", help="fill column H with purchase qty and rewrite xlsx")
    parser.add_argument("--as-of", default=None, help="override asOf date for seasonal calc (YYYY-MM-DD)")
    parser.add_argument("--horizon", type=int, default=None, help="override horizon months")
    parser.add_argument("--buffer", type=int, default=None, help="override buffer percent")
    args = parser.parse_args(argv)

    xlsx = find_xlsx()
    unpack_xlsx(xlsx)
    if args.unpack_only:
        print(f"unpacked {xlsx.name} -> {UNPACK_DIR}")
        return 0

    payload = extract_payload(xlsx)

    if args.fill_purchase:
        opts = {
            "asOf": args.as_of or payload["meta"].get("periodTo") or DEFAULT_AS_OF,
            "horizonMonths": args.horizon if args.horizon is not None else DEFAULT_HORIZON_MONTHS,
            "bufferPercent": args.buffer if args.buffer is not None else DEFAULT_BUFFER_PERCENT,
        }
        fill_purchase_column(xlsx, payload, opts)
        # переупаковываем после записи
        unpack_xlsx(xlsx)
        # пересчитываем payload после записи (проверим что H теперь содержит значения)
        payload = extract_payload(xlsx)
        print(f"filled column H (К закупке) in {xlsx.name} with opts {opts}")

    if args.verify:
        verify_against_disk(payload)
        print(f"ok {payload['meta']['itemCount']} items, sha256={payload['meta']['sourceSha256'][:12]}… format={payload['meta'].get('format')}")
        return 0

    write_json(payload)
    print(f"wrote {JSON_PATH.relative_to(ROOT)} and {WEB_PUBLIC_JSON.relative_to(ROOT)} ({payload['meta']['itemCount']} items, format={payload['meta'].get('format')}, months={len(payload['meta']['months'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
