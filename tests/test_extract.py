#!/usr/bin/env python3
"""Data-integrity tests for the unpacked «Ведомость мав» workbook."""

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

    def test_source_workbook_exists(self) -> None:
        self.assertTrue(self.xlsx.is_file())
        self.assertGreater(self.xlsx.stat().st_size, 1000)

    def test_item_count(self) -> None:
        self.assertEqual(len(self.items), 111)
        self.assertEqual(self.payload["meta"]["itemCount"], 111)
        self.assertEqual(self.payload["totals"]["items"], 111)

    def test_no_macros(self) -> None:
        self.assertFalse(self.payload["meta"]["hasVba"])
        self.assertFalse(self.payload["meta"]["hasFormulas"])

    def test_balance_identity(self) -> None:
        bad = [
            item["name"]
            for item in self.items
            if not item["balanceOk"]
        ]
        self.assertEqual(bad, [], f"balance identity failed: {bad}")

    def test_closing_equals_opening_plus_in_minus_out(self) -> None:
        for item in self.items:
            expected = round(item["opening"] + item["incoming"] - item["outgoing"], 2)
            self.assertAlmostEqual(item["closing"], expected, places=2, msg=item["name"])

    def test_months_length(self) -> None:
        self.assertEqual(len(self.payload["meta"]["months"]), 13)
        for item in self.items:
            self.assertEqual(len(item["months"]), 13)
            self.assertAlmostEqual(item["monthTotal"], round(sum(item["months"]), 2), places=2)

    def test_required_fields(self) -> None:
        for item in self.items:
            self.assertTrue(item["warehouse"])
            self.assertTrue(item["group"])
            self.assertTrue(item["name"])
            self.assertTrue(item["unit"])
            self.assertIn(item["unit"], {"шт", "банка", "ведро"})
            self.assertGreaterEqual(item["opening"], 0)
            self.assertGreaterEqual(item["incoming"], 0)
            self.assertGreaterEqual(item["outgoing"], 0)
            self.assertGreaterEqual(item["closing"], 0)

    def test_single_warehouse_and_group(self) -> None:
        warehouses = {i["warehouse"] for i in self.items}
        groups = {i["group"] for i in self.items}
        self.assertEqual(warehouses, {"Склад Кореличи"})
        self.assertEqual(groups, {"2 краски растворители"})

    def test_known_sku(self) -> None:
        brava = [i for i in self.items if i["sku"] == "094977"]
        self.assertEqual(len(brava), 1)
        self.assertEqual(brava[0]["name"], "Краска ВД-АК-1035у белый Брава")

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
