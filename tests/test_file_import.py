import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from app import generate_model_candidates, prepare_file_import_model, read_file_import_rows


class FileImportRowsTest(unittest.TestCase):
    def write_workbook(self, rows):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "supplier.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def test_empty_rows_are_skipped_and_product_name_is_preserved(self):
        path = self.write_workbook(
            [
                ["Артикул", "Наименование товара", "Цена"],
                ["MODEL-001", "Полное наименование товара MODEL-001", 5290],
                ["Раздел аксессуаров", None, None],
                [None, None, None],
                ["None", None, None],
            ]
        )

        rows = read_file_import_rows(path, "Артикул", "Цена")

        self.assertEqual([item["row_number"] for item in rows], [2, 3])
        self.assertEqual(rows[0]["source_model"], "MODEL-001")
        self.assertEqual(rows[0]["name"], "Полное наименование товара MODEL-001")
        self.assertEqual(rows[0]["price"], "5290")
        self.assertEqual(
            generate_model_candidates(prepare_file_import_model(rows[1]["source_model"], "")),
            [],
        )

    def test_model_is_used_as_name_when_name_column_is_absent(self):
        path = self.write_workbook(
            [
                ["model", "price"],
                ["ABC-123", 1000],
            ]
        )

        rows = read_file_import_rows(path, "model", "price")

        self.assertEqual(rows[0]["source_model"], "ABC-123")
        self.assertEqual(rows[0]["name"], "ABC-123")


if __name__ == "__main__":
    unittest.main()
