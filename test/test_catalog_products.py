"""Catalog draft / CSV Price Pro contract tests (no external site required)."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from models import Base
from services import attribute_assistant as assistant
from services import catalog_products as catalog


PRODUCT_HTML = '''
<html><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Товар Bosch WW1",
 "model":"WW1","brand":{"name":"Bosch"},"category":"Чужая категория",
 "image":["https://example.org/img/main.jpg", "https://example.org/img/second.jpg"],
 "offers":{"price":"15300.5"},"additionalProperty":[
 {"name":"Цвет", "value":"Белый"},{"name":"Лишнее поле", "value":"Постороннее"}]}
</script></html>'''


class CatalogProductsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/test.db")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.template = assistant.import_template_csv(
            self.db,
            "Цвет (Основные);Ширина (Размеры)\nБелый;59\nЧерный;60\n".encode("cp1251"),
            name="Стиральные машины", category="Бытовая техника > Стиральные машины",
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def _catalog(self):
        with patch.object(assistant, "fetch_public_html", return_value=(PRODUCT_HTML, "https://example.org/item")):
            batch = assistant.create_batch_from_urls(
                self.db, ["https://example.org/item"], template=self.template, purpose="catalog"
            )
        self.db.commit()
        return batch, batch.products[0]

    def test_images_are_links_only_and_price_is_normalized(self):
        batch, product = self._catalog()
        self.assertEqual(batch.input_mode, "urls")
        self.assertEqual(product.catalog_draft.price, "15300.5000")
        self.assertEqual(len(product.catalog_draft.images), 2)
        columns = {column["name"] for column in inspect(self.engine).get_columns("attribute_catalog_drafts")}
        self.assertNotIn("sku", columns)
        self.assertNotIn("special", columns)
        serialized = catalog.serialize_catalog_draft(product)
        self.assertNotIn("sku", serialized)
        self.assertNotIn("special", serialized)
        self.assertEqual(product.category_name, "Бытовая техника > Стиральные машины")
        self.assertEqual(product.sources[0].role, "external_product")
        self.assertFalse((Path(self.temp.name) / "images").exists())

    def test_all_template_fields_present_even_when_empty_no_extras_exported(self):
        _, product = self._catalog()
        check = catalog.catalog_preflight(self.db, product)
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["total_fields"], 2)
        self.assertEqual(check["blank_fields"], 1)
        self.assertEqual(check["attributes"], ["Основные|Цвет|Белый", "Размеры|Ширина|"])
        self.assertNotIn("Лишнее поле", "\n".join(check["attributes"]))

    def test_export_omits_sku_and_special_columns(self):
        batch, product = self._catalog()
        with patch.object(catalog, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name)):
            basic, _ = catalog.export_catalog_batch(self.db, batch.id, [product.id], include_attributes=False)
            self.db.commit()
            with basic.open(encoding="cp1251", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                row = next(reader)
                self.assertEqual(len(row), 8)
                self.assertEqual(list(row), list(catalog.FIELDS[:-1]))
                self.assertNotIn("_SKU_", row)
                self.assertNotIn("_SPECIAL_", row)
                self.assertEqual(row["_IMAGE_"], "https://example.org/img/main.jpg")
                self.assertEqual(row["_IMAGES_"], "https://example.org/img/second.jpg")
                self.assertEqual(row["_PRODUCT_IMAGES_"], "https://example.org/img/main.jpg,https://example.org/img/second.jpg")
            extended, _ = catalog.export_catalog_batch(self.db, batch.id, [product.id], include_attributes=True)
            self.db.commit()
            with extended.open(encoding="cp1251", newline="") as handle:
                row = next(csv.DictReader(handle, delimiter=";"))
                self.assertEqual(row["_ATTRIBUTES_"], "Основные|Цвет|Белый\nРазмеры|Ширина|")

    def test_attribute_only_csv_can_be_imported_after_base_profile(self):
        batch, product = self._catalog()
        with patch.object(catalog, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name)):
            path = catalog.export_catalog_attributes(self.db, batch.id, [product.id])
            self.db.commit()
            with path.open(encoding="cp1251", newline="") as handle:
                row = next(csv.DictReader(handle, delimiter=";"))
                self.assertEqual(list(row), ["_MODEL_", "_ATTRIBUTES_"])
                self.assertEqual(row["_ATTRIBUTES_"], "Основные|Цвет|Белый\nРазмеры|Ширина|")

    def test_changed_template_blocks_export_until_resolved(self):
        batch, product = self._catalog()
        self.template.version += 1
        self.db.flush()
        check = catalog.catalog_preflight(self.db, product)
        self.assertFalse(check["ok"])
        with patch.object(catalog, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name)):
            with self.assertRaisesRegex(ValueError, "ошибки проверки"):
                catalog.export_catalog_batch(self.db, batch.id, [product.id])

    def test_missing_or_duplicate_template_value_blocks_export(self):
        _, product = self._catalog()
        value = next(v for v in product.values if v.is_in_template)
        value.template_field_id = None
        self.db.flush()
        self.assertFalse(catalog.catalog_preflight(self.db, product)["ok"])

    def test_only_https_public_host_images_accepted(self):
        for url in ("http://example.org/img.jpg", "file:///etc/passwd", "https://localhost/x", "https://127.0.0.1/a", "https://x.invalid:abc/a"):
            self.assertEqual(catalog.safe_image_url(url, "https://example.org"), "")
        self.assertEqual(catalog.safe_image_url("/image/a.jpg#view", "https://example.org/product"), "https://example.org/image/a.jpg")

    def test_draft_updates_are_versioned_and_require_a_valid_image_url(self):
        _, product = self._catalog()
        version = product.version
        with self.assertRaises(ValueError):
            catalog.update_catalog_draft(self.db, product, {"images": ["http://example.org/image.jpg"]})
        catalog.update_catalog_draft(self.db, product, {"images": [], "price": "999,5"})
        self.assertEqual(product.catalog_draft.price, "999.5000")
        self.assertGreater(product.version, version)
        self.assertEqual(product.catalog_draft.images, [])

    def test_draft_model_is_saved_in_uppercase(self):
        _, product = self._catalog()

        catalog.update_catalog_draft(self.db, product, {"model": "hhq-m64cx"})

        self.assertEqual(product.model, "HHQ-M64CX")


if __name__ == "__main__":
    unittest.main()
