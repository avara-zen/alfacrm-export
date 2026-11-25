import json
import sqlite3
import unittest

from alfacrm_export.store import write_table


class WriteTableTest(unittest.TestCase):
    def test_columns_raw_json_and_link_tables(self):
        db = sqlite3.connect(":memory:")
        rows = [
            {"id": 1, "name": "А", "teacher_ids": [5, 6], "details": [{"x": 1}], "ok": True},
            {"id": 2, "extra": "только тут"},
        ]
        write_table(db, "lesson", rows, [{"_removed": 0}, {"_removed": 1}])

        got = db.execute('SELECT id, name, extra, ok, _removed, details, raw_json FROM lesson ORDER BY id').fetchall()
        self.assertEqual(got[0][:5], (1, "А", None, 1, 0))
        self.assertEqual(json.loads(got[0][5]), [{"x": 1}])
        self.assertEqual(json.loads(got[0][6]), rows[0])  # служебные колонки не попадают в raw_json
        self.assertEqual(got[1][:5], (2, None, "только тут", None, 1))

        links = db.execute("SELECT lesson_id, value FROM lesson__teacher_ids ORDER BY value").fetchall()
        self.assertEqual(links, [(1, 5), (1, 6)])
        # список словарей — не таблица связей, остаётся JSON в колонке
        self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='lesson__details'").fetchone())

    def test_empty_table_still_created(self):
        db = sqlite3.connect(":memory:")
        write_table(db, "regular_lesson", [])
        self.assertEqual(db.execute("SELECT count(*) FROM regular_lesson").fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
