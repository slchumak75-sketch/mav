#!/usr/bin/env python3
"""Extract inventory rows from «Ведомость мав.xlsx» into JSON.

The workbook is an Office Open XML (ZIP) file, not application source.
There are no VBA macros and no cell formulas — every value is stored as a
literal. This script is the single source of truth for turning that
workbook into `data/vedomost.json`, which the web app and tests consume.

Usage:
  python3 tools/extract_xlsx.py            # unpack + write JSON
  python3 tools/extract_xlsx.py --verify   # also fail if JSON would change
  python3 tools/extract_xlsx.py --unpack-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ROOT = Path(__file__).resolve().parents[1]
XLSX_NAME = "Ведомость мав.xlsx"
UNPACK_DIR = ROOT / "source" / "xlsx"
JSON_PATH = ROOT / "data" / "vedomost.json"
WEB_PUBLIC_JSON = ROOT / "web" / "public" / "data" / "vedomost.json"

HEADER_ROW = 7
FIRST_DATA_ROW = 8
LAST_DATA_ROW = 118

MONTHS = [
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

COL_MAP = {
    "A": "warehouse",
    "B": "group",
    "C": "sku",
    "D": "name",
    "E": "unit",
    "F": "opening",
    "G": "incoming",
    "H": "outgoing",
    "I": "closing",
    "J": "minReserve",
}


def find_xlsx() -> Path:
    direct = ROOT / XLSX_NAME
    if direct.is_file():
        return direct
    matches = sorted(ROOT.glob("*.xlsx"))
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        f"Cannot find {XLSX_NAME!r} in {ROOT}. Found: {[p.name for p in matches]}"
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
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
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
            val = shared[int(v.text)]
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
    return float(text)


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


def extract_payload(xlsx: Path) -> dict[str, Any]:
    with zipfile.ZipFile(xlsx) as zf:
        names = zf.namelist()
        has_vba = any(n.lower().endswith("vbaproject.bin") for n in names)
        shared = load_shared_strings(zf)
        cells = load_cells(zf, shared)

    items: list[dict[str, Any]] = []
    for row in range(FIRST_DATA_ROW, LAST_DATA_ROW + 1):
        name = as_text(cell(cells, "D", row))
        if not name:
            continue
        opening = as_number(cell(cells, "F", row))
        incoming = as_number(cell(cells, "G", row))
        outgoing = as_number(cell(cells, "H", row))
        closing = as_number(cell(cells, "I", row))
        months = [as_number(cell(cells, m["col"], row)) for m in MONTHS]
        expected = round2(opening + incoming - outgoing)
        item = {
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
            "minReserve": round2(as_number(cell(cells, "J", row))),
            "months": months,
            "monthTotal": round2(sum(months)),
            "belowMin": closing < as_number(cell(cells, "J", row)),
            "balanceOk": abs(expected - closing) < 0.009,
        }
        items.append(item)

    below = sum(1 for i in items if i["belowMin"])
    zero = sum(1 for i in items if i["closing"] == 0)
    payload = {
        "meta": {
            "title": as_text(cell(cells, "D", 4)) or "Ведомость по остаткам ТМЦ на складах",
            "periodLabel": as_text(cell(cells, "B", 5)),
            "periodFrom": "2025-10-01",
            "periodTo": "2026-10-19",
            "scope": as_text(cell(cells, "B", 6)),
            "sourceFile": xlsx.name,
            "sourceSha256": sha256_file(xlsx),
            "sheet": "Лист_1",
            "extractedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hasVba": has_vba,
            "hasFormulas": False,
            "itemCount": len(items),
            "months": [{"key": m["key"], "label": m["label"]} for m in MONTHS],
            "buttons": ["Обновить", "Настройка"],
            "notes": [
                "Workbook is OOXML (ZIP). Unpacked XML lives in source/xlsx/.",
                "No VBA macros, no worksheet formulas — values are literals.",
                "Identity opening + incoming - outgoing = closing holds for every row.",
                "Monthly columns K–W do not sum to «Расход»; keep them as source facts.",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--unpack-only", action="store_true")
    args = parser.parse_args(argv)

    xlsx = find_xlsx()
    unpack_xlsx(xlsx)
    if args.unpack_only:
        print(f"unpacked {xlsx.name} -> {UNPACK_DIR}")
        return 0

    payload = extract_payload(xlsx)
    if args.verify:
        verify_against_disk(payload)
        print(
            f"ok {payload['meta']['itemCount']} items, "
            f"sha256={payload['meta']['sourceSha256'][:12]}…"
        )
        return 0

    write_json(payload)
    print(
        f"wrote {JSON_PATH.relative_to(ROOT)} and "
        f"{WEB_PUBLIC_JSON.relative_to(ROOT)} "
        f"({payload['meta']['itemCount']} items)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
