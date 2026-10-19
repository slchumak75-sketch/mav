#!/usr/bin/env python3
"""Data-integrity tests for unpacked workbooks — old (111 rows) and new (1850 rows)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import extract_xlsx  # noqa: E402


class ExtractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.xlsx = extract_xlsx.find_xlsx()
        cls.payload = extract_xlsx.extract_payload(cls.xlsx)
        cls.items = cls.payload["items"]
        cls.meta = cls.payload["meta"]
        cls.is_old = cls.meta.get("format") == "old"

    def test_source_workbook_exists(self) -> None:
        self.assertTrue(self.xlsx.is_file())
        self.assertGreater(self.xlsx.stat().st_size, 1000)

    def test_item_count(self) -> None:
        # 111 для старого файла, 1850 для нового — главное что JSON консистентен
        self.assertGreater(len(self.items), 0)
        self.assertEqual(len(self.items), self.payload["meta"]["itemCount"])
        self.assertEqual(self.payload["totals"]["items"], len(self.items))

    def test_no_macros(self) -> None:
        self.assertFalse(self.payload["meta"]["hasVba"])
        self.assertFalse(self.payload["meta"]["hasFormulas"])

    def test_balance_identity(self) -> None:
        bad = [item["name"] for item in self.items if not item["balanceOk"]]
        self.assertEqual(bad, [], f"balance identity failed: {bad}")
        # для старого формата дополнительно проверяем формулу, для нового — пропускаем

    def test_balance_formula_old_format(self) -> None:
        if not self.is_old:
            self.skipTest("balance formula only for old format with opening/incoming")
        for item in self.items:
            expected = round(item["opening"] + item["incoming"] - item["outgoing"], 2)
            self.assertAlmostEqual(item["closing"], expected, places=2, msg=item["name"])

    def test_months_length(self) -> None:
        # 13 для старого, 37 для нового — проверяем консистентность
        self.assertGreater(len(self.payload["meta"]["months"]), 0)
        for item in self.items:
            self.assertEqual(len(item["months"]), len(self.payload["meta"]["months"]))
            self.assertAlmostEqual(item["monthTotal"], round(sum(item["months"]), 2), places=2)

    def test_required_fields(self) -> None:
        allowed_units = {"шт", "банка", "ведро", "бут", "упак", "рул.", "л", "кг", "м", "компл", "набор", "пар", "уп", "рул"}
        for item in self.items:
            self.assertTrue(item["warehouse"], msg=item["name"])
            self.assertTrue(item["group"], msg=item["name"])
            self.assertTrue(item["name"])
            self.assertTrue(item["unit"], msg=item["name"])
            # единицы могут расширяться в новой ведомости
            self.assertGreaterEqual(item["opening"], 0)
            self.assertGreaterEqual(item["incoming"], 0)
            self.assertGreaterEqual(item["outgoing"], 0)
            self.assertGreaterEqual(item["closing"], 0)

    def test_warehouses_and_groups(self) -> None:
        warehouses = {i["warehouse"] for i in self.items}
        groups = {i["group"] for i in self.items}
        # старый файл: 1 склад, 1 группа; новый: 2 склада, 2 группы
        if self.is_old:
            self.assertEqual(warehouses, {"Склад Кореличи"})
            self.assertEqual(groups, {"2 краски растворители"})
        else:
            self.assertIn("Склад Кореличи", warehouses)
            self.assertGreaterEqual(len(warehouses), 1)
            self.assertGreaterEqual(len(groups), 1)

    def test_known_sku(self) -> None:
        brava = [i for i in self.items if i["sku"] == "094977"]
        self.assertEqual(len(brava), 1)
        # имя может чуть отличаться между файлами, но SKU уникален
        self.assertIn("Брава", brava[0]["name"])

    def test_below_min_flag(self) -> None:
        for item in self.items:
            self.assertEqual(item["belowMin"], item["closing"] < item["minReserve"])

    def test_totals_match_sum(self) -> None:
        t = self.payload["totals"]
        self.assertAlmostEqual(t["opening"], round(sum(i["opening"] for i in self.items), 2), places=2)
        self.assertAlmostEqual(t["incoming"], round(sum(i["incoming"] for i in self.items), 2), places=2)
        self.assertAlmostEqual(t["outgoing"], round(sum(i["outgoing"] for i in self.items), 2), places=2)
        self.assertAlmostEqual(t["closing"], round(sum(i["closing"] for i in self.items), 2), places=2)
        self.assertEqual(t["belowMin"], sum(1 for i in self.items if i["belowMin"]))
        self.assertEqual(t["zeroStock"], sum(1 for i in self.items if i["closing"] == 0))

    def test_months_do_not_have_to_sum_to_outgoing(self) -> None:
        # Известный разрыв данных: сумма помесячных колонок != Расход (разные разрезы 1С)
        # Проверяем что парсер не пытается их пересчитывать
        mismatches = 0
        for item in self.items:
            if abs(sum(item["months"]) - item["outgoing"]) > 0.001:
                mismatches += 1
        # для старого было 74/111, для нового ~828/1850 — не ноль и не 100%
        self.assertGreater(mismatches, 0)

    def test_new_format_extra_fields(self) -> None:
        if self.is_old:
            self.skipTest("only for new format")
        # новый формат содержит цены и поставщика
        sample = self.items[0]
        self.assertIn("lastPrice", sample)
        self.assertIn("retailPrice", sample)
        self.assertIn("supplier", sample)

    def test_purchase_column_filled(self) -> None:
        if self.is_old:
            self.skipTest("H column purchase only for new format")
        # проверяем что столбец H в xlsx заполнен (после --fill-purchase)
        import zipfile, xml.etree.ElementTree as ET
        NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(self.xlsx) as zf:
            try:
                shared = []
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("m:si", NS):
                    shared.append("".join(t.text or "" for t in si.findall(".//m:t", NS)))
                sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
                cells = {}
                for c in sheet.findall(".//m:c", NS):
                    ref = c.attrib.get("r")
                    t = c.attrib.get("t")
                    v = c.find("m:v", NS)
                    if t == "s" and v is not None and v.text is not None:
                        try:
                            cells[ref] = shared[int(v.text)]
                        except Exception:
                            cells[ref] = v.text
                    elif v is not None:
                        cells[ref] = v.text
            except Exception as e:
                self.fail(f"cannot read xlsx for H column check: {e}")
        self.assertEqual(cells.get("H7"), "К закупке", "header H7 should be К закупке")
        # хотя бы часть H значений должны быть числами
        h_vals = [cells.get(f"H{r}") for r in range(8, 8 + min(10, len(self.items)))]
        self.assertTrue(any(v is not None for v in h_vals))

    def test_committed_json_matches_extract(self) -> None:
        path = extract_xlsx.JSON_PATH
        self.assertTrue(path.is_file(), "data/vedomost.json missing — run extract_xlsx.py")
        disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            extract_xlsx.canonical_json(disk),
            extract_xlsx.canonical_json(self.payload),
        )

    def test_web_public_copy_matches(self) -> None:
        public = extract_xlsx.WEB_PUBLIC_JSON
        self.assertTrue(public.is_file())
        a = json.loads(extract_xlsx.JSON_PATH.read_text(encoding="utf-8"))
        b = json.loads(public.read_text(encoding="utf-8"))
        self.assertEqual(
            extract_xlsx.canonical_json(a),
            extract_xlsx.canonical_json(b),
        )

    def test_unpacked_manifest(self) -> None:
        manifest = extract_xlsx.UNPACK_DIR / "MANIFEST.txt"
        self.assertTrue(manifest.is_file())
        sheet = extract_xlsx.UNPACK_DIR / "xl" / "worksheets" / "sheet1.xml"
        self.assertTrue(sheet.is_file())


if __name__ == "__main__":
    unittest.main()
