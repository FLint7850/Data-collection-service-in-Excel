import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, Donor, Brand
from services import attribute_assistant as service


class AttributeAssistantTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.temp = tempfile.TemporaryDirectory()
        self.storage_patch = patch.object(service, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name))
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def make_template(self):
        source = (
            "Цвет (Основные);Максимальная скорость отжима об./мин. (Режимы);"
            "Габариты (Размеры);Список программ (Режимы)\r\n"
            "Белый;1000;45,6х59.5 X 60;Хлопок/Быстрая\r\n"
            "Чёрный;1200;60x60x85;Шерсть\r\n"
        ).encode("cp1251")
        return service.import_template_csv(
            self.db,
            source,
            name="Стиральные машины",
            category="Бытовая техника > Стиральные машины",
        )

    def test_normalization_is_type_aware(self):
        self.assertEqual(service.normalize_value("45,60", "number"), "45.6")
        self.assertEqual(service.normalize_value("45,6 х 59.5 X 60", "dimensions"), "45.6x59.5x60")
        self.assertEqual(
            service.normalize_value("Хлопок/ Быстрая /Шерсть", composite=True),
            "Быстрая/Хлопок/Шерсть",
        )
        self.assertEqual(service.normalize_value("Красный, белый", "select"), "Красный, белый")

    def test_template_import_preserves_order_groups_and_dictionary(self):
        template = self.make_template()
        self.db.flush()
        self.assertEqual([field.name for field in template.fields], [
            "Цвет",
            "Максимальная скорость отжима об./мин.",
            "Габариты",
            "Список программ",
        ])
        self.assertEqual(template.fields[1].value_type, "number")
        self.assertEqual(template.fields[2].value_type, "dimensions")
        self.assertTrue(template.fields[3].is_composite)
        self.assertEqual([item.value for item in template.fields[0].allowed_values], ["Белый", "Чёрный"])

    def test_current_values_are_protected_and_extras_are_kept(self):
        template = self.make_template()
        source = (
            '_ID_;_NAME_;_MODEL_;_ATTRIBUTES_\r\n'
            '1;Машина;WM-100;"Основные|Цвет|Белый\nСтарое|Редкий параметр|Текст, с запятой"\r\n'
        ).encode("cp1251")
        batch = service.create_batch_from_csv(self.db, template, source, filename="products.csv")
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        extra = next(value for value in product.values if value.is_extra_attribute)
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(extra.final_value, "Текст, с запятой")
        with self.assertRaises(ValueError):
            service.update_product_value(color, action="reject")

    def test_semantic_mapping_handles_short_donor_name(self):
        template = self.make_template()
        field, confidence, _reason, _alternatives = service.map_attribute(
            self.db, template, None, "Скорость отжима, об/мин"
        )
        self.assertIsNotNone(field)
        self.assertEqual(field.name, "Максимальная скорость отжима об./мин.")
        self.assertGreaterEqual(confidence, 94)

    def test_unknown_values_are_not_created_automatically(self):
        template = self.make_template()
        color = template.fields[0]
        value, confidence, reason, suggestions = service._allowed_match(color, "Серый")
        self.assertEqual(value, "")
        self.assertEqual(confidence, 0)
        self.assertIn("справочнике", reason)
        self.assertTrue(suggestions)
        self.assertEqual(len(color.allowed_values), 2)

    def test_donor_cache_resolves_model_without_parser_monolith(self):
        brand = Brand(name="AEG", group_name="Тест")
        donor = Donor(
            brand=brand,
            legacy_id="test-donor",
            site_url="https://example.com",
            known_new_products={"LWR98165XE": {"url": "/product/lwr98165xe"}},
        )
        self.db.add(donor)
        self.db.flush()
        url, reason = service.resolve_donor_url(donor, "LWR 98165 XE")
        self.assertEqual(url, "https://example.com/product/lwr98165xe")
        self.assertIn("Кэш", reason)

    def test_list_donors_joins_through_the_owning_brand(self):
        donor = Donor(
            brand=Brand(name="AEG", group_name="Test"),
            legacy_id="listed-donor",
            site_url="https://example.com",
            start_urls=["https://example.com/catalog"],
        )
        self.db.add(donor)
        self.db.flush()
        rows = service.list_donors(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], donor.id)
        self.assertEqual(rows[0]["name"], "AEG")
        self.assertEqual(rows[0]["group_name"], "Test")

    def test_conflicting_sources_require_review(self):
        template = self.make_template()
        source = '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251")
        batch = service.create_batch_from_csv(self.db, template, source, filename="products.csv")
        product = batch.products[0]
        target = next(value for value in product.values if value.attribute_name == "Цвет")
        service.apply_candidate(
            product, target, value="Белый", confidence=96, source="A", reason="", priority=0, source_name="Цвет"
        )
        service.apply_candidate(
            product, target, value="Чёрный", confidence=95, source="B", reason="", priority=1, source_name="Цвет"
        )
        self.assertEqual(target.status, "conflict")
        self.assertEqual(target.final_value, "")


if __name__ == "__main__":
    unittest.main()

