"""检查交接资料能否按约定读取。"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    """逐行读取 UTF-8 资料，避免把行号同业务主键混用。"""
    return [
        json.loads(line)
        for line in (ROOT / "materials" / f"{name}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]


class MaterialTest(unittest.TestCase):
    def test_columns_and_ids(self):
        for name, columns in EXPECTED.items():
            with self.subTest(file=name):
                rows = load(name)
                self.assertTrue(rows)
                self.assertTrue(all(set(row) == set(columns) for row in rows))
                keys = [row["id"] for row in rows]
                self.assertTrue(all(isinstance(key, str) and key for key in keys))
                self.assertEqual(len(keys), len(set(keys)))

    def test_references(self):
        for name, column, other, multiple, index in REFERENCES:
            with self.subTest(file=name, column=column, target=other):
                valid = {row["id"] for row in load(other)}
                for row in load(name):
                    value = row[column]
                    if value is None:
                        continue
                    for reference in value if multiple else [value]:
                        self.assertIn(reference if index is None else reference[index], valid)

    def test_minutes_point_to_received_material(self):
        ids = {item["id"] for name in ("terms", "replies") for item in load(name)}
        for minute in load("minutes"):
            self.assertTrue(set(minute["basis"]) <= ids)


EXPECTED = {'terms': ['id', 'type', 'issued', 'parent', 'text'], 'replies': ['id', 'supplier', 'part', 'issued', 'heading', 'prose'], 'conditions': ['id', 'facility', 'scope', 'interval', 'detail'], 'minutes': ['id', 'time', 'state', 'vendor', 'basis', 'notes']}

REFERENCES = [('terms', 'parent', 'terms', False, None)]
