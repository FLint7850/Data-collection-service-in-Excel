import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from models import (
    AttributeAllowedValue,
    AttributeBatch,
    AttributeProduct,
    AttributeProductRevision,
    AttributeProductSource,
    AttributeTemplate,
    AttributeTemplateField,
    Base,
    Brand,
    Donor,
)
from services import attribute_assistant as service


class AttributeAssistantTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database_path = Path(self.temp.name) / "attribute-assistant-test.db"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
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

    def test_template_structure_can_be_serialized_without_dictionary_values(self):
        template = self.make_template()
        counts = {field.id: len(field.allowed_values) for field in template.fields}
        payload = service.serialize_template(
            template,
            include_values=True,
            include_allowed_values=False,
            allowed_value_counts=counts,
        )
        self.assertTrue(all(not field["allowed_values"] for field in payload["fields"]))
        self.assertEqual(
            [field["allowed_values_count"] for field in payload["fields"]],
            [counts[field.id] for field in template.fields],
        )

    def test_product_detail_loads_allowed_values_lazily(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        payload = service.serialize_product(product, detailed=True)
        color = next(item for item in payload["values"] if item["name"] == "Цвет")

        self.assertEqual(color["allowed_values_count"], 2)
        self.assertEqual(color["allowed_values"], [])
        standalone = service.serialize_value(product.values[0])
        self.assertEqual([item["value"] for item in standalone["allowed_values"]], ["Белый", "Чёрный"])
    def test_current_values_remain_history_while_final_value_can_change(self):
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
        service.update_product_value(color, action="accept", manual_value="Чёрный")

        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Чёрный")
        self.assertEqual(color.status, "approved")
        serialized = service.serialize_value(color)
        self.assertEqual(
            [item["value"] for item in serialized["allowed_values"]],
            ["Белый", "Чёрный"],
        )

    def test_full_export_keeps_every_product_and_ready_export_filters(self):
        template = self.make_template()
        source = (
            '_MODEL_;_ATTRIBUTES_\r\n'
            'READY;"Основные|Цвет|Белый\n'
            'Режимы|Максимальная скорость отжима об./мин.|1000\n'
            'Размеры|Габариты|45.6x59.5x60\n'
            'Режимы|Список программ|Быстрая/Хлопок"\r\n'
            'DRAFT;"Основные|Цвет|Белый"\r\n'
        ).encode("cp1251")
        batch = service.create_batch_from_csv(self.db, template, source, filename="products.csv")

        full = service.export_batch_csv(batch, ready_only=False).read_text(encoding="cp1251")
        ready = service.export_batch_csv(batch, ready_only=True).read_text(encoding="cp1251")

        self.assertIn("READY", full)
        self.assertIn("DRAFT", full)
        self.assertIn("READY", ready)
        self.assertNotIn("DRAFT", ready)

    def test_allowed_value_revision_is_compact_and_restorable(self):
        template = self.make_template()
        allowed = template.fields[0].allowed_values[0]
        original_active = allowed.is_active
        revision = service.save_allowed_value_revision(
            self.db, allowed, "before_dictionary_edit"
        )
        self.db.flush()

        self.assertEqual(revision.snapshot["kind"], "allowed_value")
        self.assertNotIn("fields", revision.snapshot)
        self.assertLess(len(json.dumps(revision.snapshot, ensure_ascii=False)), 2_000)

        allowed.is_active = not original_active
        template.version += 1
        service.restore_template_revision(self.db, template, revision)

        self.assertEqual(allowed.is_active, original_active)
        self.assertEqual(template.revisions[-1].snapshot["kind"], "allowed_value")

    def test_semantic_mapping_handles_short_donor_name(self):
        template = self.make_template()
        field, confidence, _reason, _alternatives = service.map_attribute(
            self.db, template, None, "Скорость отжима, об/мин"
        )
        self.assertIsNotNone(field)
        self.assertEqual(field.name, "Максимальная скорость отжима об./мин.")
        self.assertGreaterEqual(confidence, 94)

    def test_attribute_name_synonyms_are_saved_used_and_copied(self):
        template = service.import_template_csv(
            self.db,
            (
                "Диаметр загрузочного люка, см (Основные);Цвет (Основные)\r\n"
                "31;Белый\r\n"
            ).encode("cp1251"),
            name="Стиральные машины",
            category="Стиральные машины",
        )
        diameter = next(
            field for field in template.fields
            if field.name == "Диаметр загрузочного люка, см"
        )
        source_name = "Диаметр загрузочного проема"
        updates = service.validate_template_field_update(
            self.db,
            diameter,
            {"synonyms": [source_name, source_name, diameter.name]},
        )
        for key, value in updates.items():
            setattr(diameter, key, value)
        self.db.flush()

        self.assertEqual(diameter.synonyms, [source_name])
        serialized = service.serialize_template(template, include_values=True)
        serialized_field = next(
            field for field in serialized["fields"] if field["id"] == diameter.id
        )
        self.assertEqual(serialized_field["synonyms"], [source_name])

        mapped, confidence, reason, _alternatives = service.map_attribute(
            self.db,
            template,
            None,
            source_name,
            "310 мм",
        )
        self.assertEqual(mapped, diameter)
        self.assertEqual(confidence, 100)
        self.assertIn("Синоним", reason)

        copied = service.copy_template(self.db, template, name="Копия с синонимами")
        copied_diameter = next(
            field for field in copied.fields if field.name == diameter.name
        )
        self.assertEqual(copied_diameter.synonyms, [source_name])

        revision = service.save_template_revision(
            self.db,
            template,
            "before_synonym_change",
        )
        self.db.flush()
        diameter.synonyms = []
        template.version += 1
        service.restore_template_revision(self.db, template, revision)
        self.assertEqual(diameter.synonyms, [source_name])

        color = next(field for field in template.fields if field.name == "Цвет")
        with self.assertRaisesRegex(ValueError, "уже относится"):
            service.validate_template_field_update(
                self.db,
                color,
                {"synonyms": [source_name]},
            )

    def test_semantic_mapping_normalizes_inflections_and_abbreviations(self):
        template = service.import_template_csv(
            self.db,
            (
                "Размораживание морозильной камеры (Морозильная камера);"
                "Количество ящиков морозильного отделения, шт (Морозильная камера);"
                "Режим «Суперзаморозка» (Морозильная камера);"
                "Габариты ниши для встраивания (ВхШхГ), см (Габариты)\r\n"
                "Автоматическая;3;Да;177.5x56x55\r\n"
            ).encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        cases = {
            "Система размораживания м.к.": "Размораживание морозильной камеры",
            "Количество ящиков в морозильной камере": "Количество ящиков морозильного отделения, шт",
            "Функция суперзамораживание (super freezing)": "Режим «Суперзаморозка»",
            "Размер ниши для встраивания (В х Ш х Г), см": "Габариты ниши для встраивания (ВхШхГ), см",
        }
        for source_name, expected in cases.items():
            with self.subTest(source_name=source_name):
                field, confidence, _reason, _alternatives = service.map_attribute(
                    self.db, template, None, source_name
                )
                self.assertIsNotNone(field)
                self.assertEqual(field.name, expected)
                self.assertGreaterEqual(confidence, 94)

    def test_chatgpt_context_receives_close_names_rejected_by_automatic_mapping(self):
        from services import attribute_ai

        allowed_values = [str(value) for value in range(1, 41)]
        template = service.import_template_csv(
            self.db,
            (
                "Диаметр загрузочного люка, см (Основные)\r\n"
                + "\r\n".join(allowed_values)
                + "\r\n"
            ).encode("cp1251"),
            name="Стиральные машины",
            category="Стиральные машины",
        )
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nW7096XW;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        source_name = "Диаметр загрузочного проема"
        field, _confidence, _reason, _alternatives = service.map_attribute(
            self.db,
            template,
            None,
            source_name,
            "310 мм",
        )
        self.assertIsNone(field)

        prompt, _evidence = attribute_ai.build_product_prompt(
            batch.products[0],
            source_url="https://example.com/w7096xw",
            parsed={"attributes": [{"name": source_name, "value": "310 мм"}]},
        )
        context = json.loads(prompt.split("КОНТЕКСТ ДЛЯ АНАЛИЗА:\n", 1)[1])
        prompt_field = next(
            item
            for item in context["template_fields"]
            if item["name"] == "Диаметр загрузочного люка, см"
        )
        catalog_field = next(
            item
            for item in context["template_field_catalog"]
            if item["name"] == "Диаметр загрузочного люка, см"
        )
        self.assertEqual(catalog_field["id"], prompt_field["id"])
        self.assertIn(
            {"name": source_name, "value": "310 мм"},
            prompt_field["source_hints"],
        )
        self.assertIn("31", prompt_field["allowed_values"])

        analysis = attribute_ai.validate_analysis(
            batch.products[0],
            {
                "attributes": [
                    {
                        "name": source_name,
                        "field_id": prompt_field["id"],
                        "value": "310 мм",
                        "confidence": 84,
                        "evidence": f"{source_name}: 310 мм",
                    }
                ]
            },
            page_evidence=f"{source_name}: 310 мм",
        )
        self.assertEqual(len(analysis["suggestions"]), 1)
        self.assertEqual(analysis["suggestions"][0]["proposed_value"], "31")

    def test_unique_dictionary_value_can_disambiguate_short_attribute_name(self):
        template = service.import_template_csv(
            self.db,
            (
                "Тип установки (Основные);Вид (Основные)\r\n"
                "Встраиваемый;Двухкамерный\r\n"
            ).encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        field, confidence, reason, _alternatives = service.map_attribute(
            self.db, template, None, "Тип", "встраиваемый"
        )
        self.assertIsNotNone(field)
        self.assertEqual(field.name, "Тип установки")
        self.assertGreaterEqual(confidence, 90)
        self.assertIn("справочника", reason)

    def test_specific_feature_does_not_map_to_generic_one_word_field(self):
        template = service.import_template_csv(
            self.db,
            (
                "Тип управления (Основные);Дисплей (Основные)\r\n"
                "Электронное;Да\r\n"
            ).encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        field, _confidence, reason, _alternatives = service.map_attribute(
            self.db,
            template,
            None,
            "Управление через Вай-Фай (home connect)",
            "есть",
        )
        self.assertIsNone(field)
        self.assertIn("схожесть", reason)

    def test_extra_object_words_prevent_false_attribute_mapping(self):
        template = service.import_template_csv(
            self.db,
            (
                "Количество дверей (Основные);Общее количество полок, шт (Камера)\r\n"
                "2;5\r\n"
            ).encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        field, confidence, _reason, alternatives = service.map_attribute(
            self.db,
            template,
            None,
            "Количество полок на дверце",
            "4",
        )
        self.assertIsNone(field)
        self.assertLess(confidence, 74)
        self.assertTrue(alternatives)

    def test_manual_allowed_value_search_and_selection(self):
        template = self.make_template()
        color = template.fields[0]
        options = service.allowed_value_options(color, "бел")
        self.assertEqual([item["value"] for item in options["values"]], ["Белый"])
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        value = next(item for item in batch.products[0].values if item.attribute_name == "Цвет")
        service.update_product_value(value, action="accept", manual_value="Белый")
        self.assertEqual(value.final_value, "Белый")
        self.assertEqual(value.status, "approved")

    def test_allowed_value_synonyms_can_be_replaced_and_removed(self):
        template = self.make_template()
        allowed = template.fields[0].allowed_values[0]

        service.replace_allowed_value_synonyms(
            self.db,
            allowed,
            ["белая", " White ", "БЕЛАЯ", "Белый", ""],
        )
        self.assertEqual([item.synonym for item in allowed.synonyms], ["белая", "White"])

        service.replace_allowed_value_synonyms(self.db, allowed, ["Снежный"])
        self.assertEqual([item.synonym for item in allowed.synonyms], ["Снежный"])

        service.replace_allowed_value_synonyms(self.db, allowed, [])
        self.assertEqual(allowed.synonyms, [])

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

    def test_resolve_donor_url_crawls_from_site_root_to_exact_product(self):
        donor = Donor(
            brand=Brand(name="Bosch", group_name="Test"),
            legacy_id="bosch-test",
            site_url="https://example.com/",
            start_urls=["https://example.com/washing-machines"],
        )
        self.db.add(donor)
        self.db.flush()

        pages = {
            "https://example.com/": '<a href="/catalog/fridges/">Холодильники</a>',
            "https://example.com/catalog/fridges/": (
                '<a href="/catalog/fridges/bosch-kin86hdf0.html">'
                'Двухкамерный холодильник Bosch KIN86HDF0</a>'
            ),
            "https://example.com/washing-machines": '<a href="/catalog/washers/">Стиральные машины</a>',
        }

        def fake_fetch(url, *args, **kwargs):
            if url not in pages:
                raise RuntimeError("not found")
            return pages[url], url

        with patch.object(service, "_find_in_sitemaps", return_value=""), patch.object(
            service, "fetch_public_html", side_effect=fake_fetch
        ):
            url, reason = service.resolve_donor_url(
                donor,
                "KIN86HDF0",
                product_name="Двухкамерный холодильник Bosch KIN86HDF0",
                category="Холодильники",
            )

        self.assertEqual(url, "https://example.com/catalog/fridges/bosch-kin86hdf0.html")
        self.assertIn("обходе каталога", reason)

    def test_repeated_donor_processing_replaces_old_source_before_insert(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Test donor", group_name="Test"),
            legacy_id="repeat-test",
            site_url="https://example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]

        with patch.object(service, "resolve_donor_url", return_value=("", "not found")):
            service.process_product_donors(self.db, product, [donor.id])
            self.db.flush()
            service.process_product_donors(self.db, product, [donor.id])
            self.db.flush()

        non_own = [source for source in product.sources if source.role != "own_site"]
        self.assertEqual(len(non_own), 1)
        self.assertEqual(non_own[0].status, "not_found")

    def test_semantic_characteristic_rows_are_extracted_without_tooltip_text(self):
        html = """
        <h1>Bosch KIN86HDF0</h1>
        <div class="characteristics__row">
          <span class="characteristics__name">Цвет</span>
          <span class="characteristics__property">
            Белый
            <span class="glossary-tooltip"><b>Цвет</b> — длинная справка</span>
          </span>
        </div>
        """
        parsed = service.parse_product_html(html, "https://example.com/product")
        self.assertEqual(parsed["attributes"], [
            {"name": "Цвет", "value": "Белый", "group": ""}
        ])

    def test_structural_two_column_characteristics_are_extracted_without_site_classes(self):
        html = """
        <h1>WM-100</h1>
        <h2>Характеристики товара</h2>
        <div class="arbitrary-wrapper">
          <h3>Основные</h3>
          <div class="arbitrary-list">
            <div class="arbitrary-row"><div>Цвет</div><div>Белый</div></div>
            <div class="arbitrary-row"><div>Редкий параметр</div><div>Особое значение</div></div>
          </div>
        </div>
        """

        parsed = service.parse_product_html(html, "https://example.com/product")

        self.assertEqual(parsed["attributes"], [
            {"name": "Цвет", "value": "Белый", "group": "Основные"},
            {"name": "Редкий параметр", "value": "Особое значение", "group": "Основные"},
        ])

    def test_url_import_uses_own_page_as_current_values_and_counts_outside_template(self):
        template = self.make_template()
        html = """
        <h1>WM-100</h1>
        <h2>Характеристики товара</h2>
        <section>
          <h3>Основные</h3>
          <div><div><span>Цвет</span></div><div>Белый</div></div>
          <div><div>Скорость отжима, об/мин</div><div>1000</div></div>
          <div><div>Редкий параметр</div><div>Особое значение</div></div>
        </section>
        """
        with patch.object(
            service,
            "fetch_public_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ):
            batch = service.create_batch_from_urls(
                self.db,
                ["https://example.com/products/wm-100"],
                template=template,
            )

        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        speed = next(
            value for value in product.values
            if value.attribute_name == "Максимальная скорость отжима об./мин."
        )
        extra = next(value for value in product.values if value.is_extra_attribute)
        payload = service.serialize_product(product)
        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(speed.current_value, "1000")
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.source, "current_site")
        self.assertEqual(extra.current_value, "Особое значение")
        self.assertEqual(payload["counts"]["outside_template"], 1)

        extra_id = extra.id
        service.delete_extra_product_value(self.db, extra)
        self.assertIsNone(self.db.get(type(extra), extra_id))
        self.assertEqual(service.serialize_product(product)["counts"]["outside_template"], 0)
        self.assertEqual(service.restore_cached_site_current_values(product), 0)
        self.assertFalse(any(not value.is_in_template for value in product.values))
        with self.assertRaisesRegex(ValueError, "только атрибуты вне шаблона"):
            service.delete_extra_product_value(self.db, color)

    def test_cached_url_attributes_can_backfill_current_values(self):
        template = self.make_template()
        html = """
        <h1>WM-100</h1>
        <h2>Характеристики</h2>
        <div><div><div>Цвет</div><div>Белый</div></div></div>
        """
        with patch.object(
            service,
            "fetch_public_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ):
            batch = service.create_batch_from_urls(
                self.db,
                ["https://example.com/products/wm-100"],
                template=template,
            )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        color.current_value = ""
        color.final_value = ""
        color.source = ""
        color.status = "missing"

        changed = service.restore_cached_site_current_values(product)

        self.assertEqual(changed, 1)
        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.source, "current_site")
    def test_url_import_does_not_mix_processing_events_with_product_revisions(self):
        template = self.make_template()
        html = """
        <h1>WM-100</h1>
        <div class="characteristics__row">
          <span class="characteristics__name">Гарантия, мес</span>
          <span class="characteristics__property">12</span>
        </div>
        """
        with patch.object(
            service,
            "fetch_public_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ):
            batch = service.create_batch_from_urls(
                self.db,
                ["https://example.com/products/wm-100"],
                template=template,
            )

        revisions = self.db.query(AttributeProductRevision).all()
        self.assertEqual(revisions, [])
        self.assertEqual(len(batch.products), 1)

    def test_find_and_check_opens_product_page_and_applies_attributes(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Official donor", group_name="Test"),
            legacy_id="parse-product-test",
            site_url="https://example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]
        html = """
        <h1>WM-100</h1>
        <div class="characteristics__row">
          <span class="characteristics__name">Цвет</span>
          <span class="characteristics__property">Белый</span>
        </div>
        """
        with patch.object(
            service,
            "resolve_donor_url",
            return_value=("https://example.com/products/wm-100", "Найдена по модели"),
        ), patch.object(
            service,
            "fetch_public_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ):
            report = service.process_product_donors(self.db, product, [donor.id])

        color = next(value for value in product.values if value.attribute_name == "Цвет")
        donor_report = report["reports"][0]
        self.assertEqual(donor_report["status"], "parsed")
        self.assertEqual(donor_report["attributes_found"], 1)
        self.assertEqual(donor_report["mapped"], 1)
        self.assertEqual(color.proposed_value, "Белый")
        self.assertEqual(product.sources[0].status, "parsed")
        self.assertEqual(len(product.sources[0].parsed_data["attributes"]), 1)

    def test_donor_processing_reuses_caller_owned_fetcher(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Shared fetcher donor", group_name="Test"),
            legacy_id="shared-fetcher",
            site_url="https://example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        marker = object()
        html = '<h1>WM-100</h1><table><tr><th>Цвет</th><td>Белый</td></tr></table>'
        with patch.object(
            service,
            "resolve_donor_url",
            return_value=("https://example.com/products/wm-100", "Найдена по модели"),
        ), patch.object(
            service,
            "fetch_donor_product_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ) as fetch:
            service.process_product_donors(
                self.db,
                batch.products[0],
                [donor.id],
                fetcher=marker,
            )

        self.assertIs(fetch.call_args.kwargs["fetcher"], marker)

    def test_chatgpt_prefers_selected_donor_over_own_site_url(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Official donor", group_name="Test"),
            legacy_id="preferred-chatgpt-source",
            site_url="https://official.example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]
        product.source_url = "https://shop.example.com/wm-100"
        product.sources.extend([
            AttributeProductSource(
                url=product.source_url,
                priority=0,
                role="own_site",
                status="parsed",
                parsed_data={"attributes": []},
            ),
            AttributeProductSource(
                donor=donor,
                url="https://official.example.com/wm-100",
                priority=0,
                role="primary",
                status="parsed",
                parsed_data={"attributes": [{"name": "Цвет", "value": "Белый"}]},
            ),
        ])
        html = '<div class="characteristics__row"><span class="characteristics__name">Цвет</span><span class="characteristics__property">Белый</span></div>'
        with patch.object(
            attribute_ai,
            "ATTRIBUTE_ASSISTANT_DIR",
            Path(self.temp.name),
        ), patch.object(
            attribute_ai,
            "fetch_donor_product_html",
            return_value=(html, "https://official.example.com/wm-100"),
        ):
            source_url, _html, _parsed, _reason = attribute_ai.prepare_product_source(
                self.db, product, [donor.id]
            )
        prompt, _evidence = attribute_ai.build_product_prompt(product, source_url=source_url, html=html)
        self.assertEqual(source_url, "https://official.example.com/wm-100")
        self.assertIn('"official_product_url":"https://official.example.com/wm-100"', prompt)

    def test_chatgpt_uses_current_manual_url_without_parser_run(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nW7096XW;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Asko", group_name="Test"),
            legacy_id="chatgpt-manual-url",
            site_url="https://asko.example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]
        product.sources.append(
            AttributeProductSource(
                donor=donor,
                url="https://asko.example.com/old-product",
                priority=0,
                role="primary",
                status="parsed",
                parsed_data={"attributes": [{"name": "Цвет", "value": "Старый"}]},
            )
        )
        manual_url = "https://asko.example.com/w7096xw"
        html = "<h1>W7096XW</h1><table><tr><th>Цвет</th><td>Белый</td></tr></table>"

        with patch.object(
            attribute_ai,
            "ATTRIBUTE_ASSISTANT_DIR",
            Path(self.temp.name),
        ), patch.object(
            attribute_ai,
            "resolve_donor_url",
        ) as resolve, patch.object(
            attribute_ai,
            "fetch_donor_product_html",
            return_value=(html, manual_url),
        ):
            source_url, _html, parsed, reason = attribute_ai.prepare_product_source(
                self.db,
                product,
                [donor.id],
                url_overrides={str(donor.id): manual_url},
            )

        resolve.assert_not_called()
        self.assertEqual(source_url, manual_url)
        self.assertEqual(reason, "Ссылка задана пользователем")
        self.assertEqual(parsed["model"], "W7096XW")
        self.assertEqual(product.selected_donor_ids, [donor.id])
        self.assertEqual(product.donor_url_overrides, {str(donor.id): manual_url})

    def test_chatgpt_verifies_values_already_found_by_parser(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            (
                '_MODEL_;_ATTRIBUTES_\r\n'
                'WM-100;"Основные|Цвет|Белый"\r\n'
            ).encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        parsed = {"attributes": [{"name": "Цвет", "value": "Белый"}]}
        prompt, evidence = attribute_ai.build_product_prompt(
            product,
            source_url="https://example.com/products/wm-100",
            html="<div>Цвет: Белый</div>",
            parsed=parsed,
        )
        context = json.loads(prompt.split("КОНТЕКСТ ДЛЯ АНАЛИЗА:\n", 1)[1])
        prompt_field = next(item for item in context["template_fields"] if item["id"] == color.template_field_id)
        self.assertEqual(prompt_field["current_value"], "Белый")
        self.assertEqual(
            context["parser_attributes"],
            [{"source_id": 1, "name": "Цвет", "value": "Белый"}],
        )

        analysis = attribute_ai.validate_analysis(
            product,
            {
                "attributes": [
                    {
                        "source_id": 1,
                        "field_id": color.template_field_id,
                        "confidence": 82,
                    }
                ],
                "warnings": [],
            },
            page_evidence=evidence,
            source_facts=context["parser_attributes"],
        )
        changed = attribute_ai.apply_analysis(
            self.db,
            product,
            analysis,
            source_url="https://example.com/products/wm-100",
        )
        self.assertEqual(changed, 1)
        self.assertEqual(color.status, "kept")
        self.assertTrue(any(item["source"] == "ChatGPT" for item in color.source_details["candidates"]))

    def test_chatgpt_conflict_does_not_overwrite_manual_final_value(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        service.update_product_value(color, action="accept", manual_value="Белый")
        analysis = attribute_ai.validate_analysis(
            product,
            {
                "attributes": [
                    {
                        "name": "Цвет",
                        "field_id": color.template_field_id,
                        "value": "Чёрный",
                        "confidence": 80,
                        "evidence": "Цвет: Чёрный",
                    }
                ]
            },
            page_evidence="Цвет: Чёрный",
        )
        attribute_ai.apply_analysis(
            self.db,
            product,
            analysis,
            source_url="https://example.com/products/wm-100",
        )
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.status, "conflict")
        self.assertTrue(any(item["source"] == "ChatGPT" for item in color.source_details["candidates"]))
    def test_chatgpt_reuses_saved_parser_snapshot(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Official donor", group_name="Test"),
            legacy_id="saved-chatgpt-source",
            site_url="https://official.example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        raw_path = Path(self.temp.name) / "saved-page.html"
        raw_path.write_text("<div>Цвет: Белый</div>", encoding="utf-8")
        product = batch.products[0]
        product.sources.append(
            AttributeProductSource(
                donor=donor,
                url="https://official.example.com/wm-100",
                priority=0,
                role="primary",
                status="parsed",
                raw_html_path=str(raw_path),
                parsed_data={"attributes": [{"name": "Цвет", "value": "Белый"}]},
            )
        )

        with patch.object(attribute_ai, "fetch_donor_product_html") as fetch:
            source_url, html, parsed, _reason = attribute_ai.prepare_product_source(
                self.db, product, [donor.id]
            )
        fetch.assert_not_called()
        self.assertEqual(source_url, "https://official.example.com/wm-100")
        self.assertIn("Цвет: Белый", html)
        self.assertEqual(parsed["attributes"], [{"name": "Цвет", "value": "Белый"}])
    def test_chatgpt_source_resolution_persists_exact_product_url(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Test donor", group_name="Test"),
            legacy_id="chatgpt-source-test",
            site_url="https://example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]
        html = '<h1>WM-100</h1><table><tr><th>Цвет</th><td>Белый</td></tr></table>'
        with patch.object(
            attribute_ai,
            "ATTRIBUTE_ASSISTANT_DIR",
            Path(self.temp.name),
        ), patch.object(
            attribute_ai,
            "resolve_donor_url",
            return_value=("https://example.com/products/wm-100", "Найдена по модели"),
        ), patch.object(
            attribute_ai,
            "fetch_donor_product_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ):
            source_url, page_html, parsed, reason = attribute_ai.prepare_product_source(
                self.db, product, [donor.id]
            )

        self.db.flush()
        self.assertEqual(source_url, "https://example.com/products/wm-100")
        self.assertEqual(page_html, html)
        self.assertEqual(parsed["model"], "WM-100")
        self.assertIn("модели", reason)
        self.assertEqual(len(product.sources), 1)
        self.assertEqual(product.sources[0].status, "parsed")
        self.assertEqual(product.sources[0].url, source_url)

    def test_chatgpt_source_download_reuses_caller_owned_fetcher(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Shared ChatGPT donor", group_name="Test"),
            legacy_id="shared-chatgpt-fetcher",
            site_url="https://example.com/",
        )
        self.db.add(donor)
        self.db.flush()
        marker = object()
        html = '<h1>WM-100</h1><table><tr><th>Цвет</th><td>Белый</td></tr></table>'
        with patch.object(
            attribute_ai,
            "ATTRIBUTE_ASSISTANT_DIR",
            Path(self.temp.name),
        ), patch.object(
            attribute_ai,
            "resolve_donor_url",
            return_value=("https://example.com/products/wm-100", "Найдена по модели"),
        ), patch.object(
            attribute_ai,
            "fetch_donor_product_html",
            return_value=(html, "https://example.com/products/wm-100"),
        ) as fetch:
            attribute_ai.prepare_product_source(
                self.db,
                batch.products[0],
                [donor.id],
                fetcher=marker,
            )

        self.assertIs(fetch.call_args.kwargs["fetcher"], marker)

    def test_chatgpt_analysis_accepts_only_template_dictionary_values(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        response = {
            "attributes": [
                {
                    "name": "Цвет",
                    "field_id": color.template_field_id,
                    "value": "Белый",
                    "confidence": 82,
                    "evidence": "Цвет: Белый",
                },
                {
                    "name": "Цвет",
                    "field_id": color.template_field_id,
                    "value": "Серый",
                    "confidence": 80,
                    "evidence": "Цвет: Серый",
                },
            ],
            "warnings": [],
        }
        analysis = attribute_ai.validate_analysis(
            product, response, page_evidence="Характеристики товара\nЦвет: Белый"
        )
        changed = attribute_ai.apply_analysis(
            self.db, product, analysis, source_url="https://example.com/product/wm-100"
        )
        self.assertEqual(changed, 1)
        self.assertEqual(color.proposed_value, "Белый")
        self.assertEqual(color.source, "ChatGPT")
        chatgpt_source = next(source for source in product.sources if source.role == "chatgpt")
        self.assertEqual(chatgpt_source.status, "parsed")
        self.assertEqual(chatgpt_source.parsed_data["processing_stats"]["mapped"], 1)
        serialized_source = next(
            source for source in service.serialize_product(product, detailed=True)["sources"]
            if source["source_type"] == "chatgpt"
        )
        self.assertEqual(serialized_source["donor_name"], "ChatGPT")

    def test_chatgpt_compact_response_preserves_raw_facts_and_normalizes_values(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        raw_values = ["Белый", "1000", "45,6 х 59.5 X 60", "Хлопок / Быстрая"]
        records = [
            {"name": field.name, "value": value, "field_id": field.id,
             "confidence": 82, "evidence": f"{field.name}: {value}"}
            for field, value in zip(template.fields, raw_values)
        ]
        records.append({"name": "Особенность", "value": "Технология ABC", "field_id": None,
                        "evidence": "Особенность: Технология ABC"})
        evidence = "\n".join(item["evidence"] for item in records)
        analysis = attribute_ai.validate_analysis(
            product, json.dumps({"attributes": records}), page_evidence=evidence,
        )
        self.assertEqual(analysis["warnings"], [])
        self.assertEqual(len(analysis["observed_attributes"]), 5)
        self.assertEqual(
            [item["proposed_value"] for item in analysis["suggestions"]],
            ["Белый", "1000", "45.6x59.5x60", "Быстрая/Хлопок"],
        )
        self.assertEqual(analysis["observed_attributes"][2]["value"], raw_values[2])
        changed = attribute_ai.apply_analysis(
            self.db, product, analysis, source_url="https://example.com/wm-100",
        )
        self.assertEqual(changed, 4)
        source = next(item for item in product.sources if item.role == "chatgpt")
        self.assertEqual(source.parsed_data["attributes"], analysis["observed_attributes"])
        for value in product.values:
            self.assertTrue(value.source_details["chatgpt"]["evidence"] in evidence)

    def test_chatgpt_compact_response_accepts_dictionary_choice_without_losing_raw_value(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        record = {"name": "Оттенок корпуса", "value": "светлый", "field_id": template.fields[0].id,
                  "allowed_value": "Белый", "confidence": 81, "evidence": "Оттенок корпуса: светлый"}
        analysis = attribute_ai.validate_analysis(
            batch.products[0], {"attributes": [record]}, page_evidence=record["evidence"],
        )
        self.assertEqual(analysis["warnings"], [])
        self.assertEqual(analysis["observed_attributes"][0]["value"], "светлый")
        self.assertEqual(len(analysis["suggestions"]), 1)
        suggestion = analysis["suggestions"][0]
        self.assertEqual(suggestion["proposed_value"], "Белый")
        self.assertEqual(suggestion["source_name"], "Оттенок корпуса")
        self.assertEqual(suggestion["confidence"], 81)
        self.assertEqual(suggestion["evidence"], record["evidence"])

    def test_chatgpt_compact_response_rejects_unknown_inactive_and_foreign_values(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        color = template.fields[0]
        next(item for item in color.allowed_values if item.value == "Белый").is_active = False
        original_values = [(item.id, item.value, item.is_active) for item in color.allowed_values]
        for allowed in (None, "Серый", "Белый", "1000"):
            with self.subTest(allowed_value=allowed):
                record = {"name": "Цвет", "value": "светлый", "field_id": color.id,
                          "allowed_value": allowed, "evidence": "Цвет: светлый"}
                analysis = attribute_ai.validate_analysis(
                    batch.products[0], {"attributes": [record]}, page_evidence=record["evidence"],
                )
                self.assertEqual(analysis["suggestions"], [])
                self.assertEqual(len(analysis["observed_attributes"]), 1)
                self.assertTrue(any("нет в справочнике" in item for item in analysis["warnings"]))
        self.assertEqual(original_values, [(item.id, item.value, item.is_active) for item in color.allowed_values])

    def test_chatgpt_compact_response_validates_quote_name_value_and_field(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        record = {"name": "Цвет", "value": "Белый", "field_id": template.fields[0].id,
                  "confidence": 82, "evidence": "Цвет: Белый"}
        for change in ({"name": ""}, {"value": ""}, {"evidence": ""}, {"evidence": "Цвет: Чёрный"}):
            with self.subTest(change=change):
                analysis = attribute_ai.validate_analysis(
                    batch.products[0], {"attributes": [dict(record, **change)]},
                    page_evidence=record["evidence"],
                )
                self.assertEqual(analysis["observed_attributes"], [])
                self.assertEqual(analysis["suggestions"], [])
                self.assertTrue(analysis["warnings"])
        for change in ({"field_id": 999999}, {"field_id": True}, {"field_id": 1.5}, {"confidence": "bad"}):
            with self.subTest(change=change):
                analysis = attribute_ai.validate_analysis(
                    batch.products[0], {"attributes": [dict(record, **change)]},
                    page_evidence=record["evidence"],
                )
                self.assertEqual(len(analysis["observed_attributes"]), 1)
                self.assertEqual(analysis["suggestions"], [])
                self.assertTrue(analysis["warnings"])

    def test_chatgpt_requires_one_compact_response_format(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        for response in ({}, {"observed_attributes": [], "mapped_attributes": [], "suggestions": []},
                         {"attributes": None}, {"attributes": {}}, {"attributes": "[]"}):
            with self.subTest(response=response):
                with self.assertRaisesRegex(ValueError, "массив attributes"):
                    attribute_ai.validate_analysis(batch.products[0], response)
        analysis = attribute_ai.validate_analysis(batch.products[0], {"attributes": [], "warnings": ["Нет данных"]})
        self.assertEqual(analysis["suggestions"], [])
        self.assertEqual(analysis["observed_attributes"], [])
        self.assertEqual(analysis["warnings"], ["Нет данных"])
        for prompt in (attribute_ai.UNIVERSAL_ATTRIBUTE_PROMPT,):
            self.assertIn('"attributes"', prompt)
            self.assertIn("allowed_value", prompt)
            for old_section in ("observed_attributes", "mapped_attributes", "suggestions"):
                self.assertNotIn(old_section, prompt)

    def test_chatgpt_raw_dictionary_match_takes_priority_and_duplicates_are_ignored(self):
        from services import attribute_ai

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        record = {"name": "Цвет", "value": "Белый", "field_id": template.fields[0].id,
                  "allowed_value": "Чёрный", "confidence": 99, "evidence": "Цвет: Белый"}
        analysis = attribute_ai.validate_analysis(
            batch.products[0], {"attributes": [record, record]}, page_evidence=record["evidence"],
        )
        self.assertEqual(len(analysis["observed_attributes"]), 1)
        self.assertEqual(len(analysis["suggestions"]), 1)
        self.assertEqual(analysis["suggestions"][0]["proposed_value"], "Белый")
        self.assertEqual(analysis["suggestions"][0]["confidence"], 85)

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


    def test_donor_candidates_are_kept_for_protected_current_value(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            (
                '_MODEL_;_ATTRIBUTES_\r\n'
                'WM-100;"Основные|Цвет|Белый"\r\n'
            ).encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")

        stats = service.apply_parsed_attributes(
            self.db,
            product,
            [{"name": "Цвет", "value": "белый"}],
            source="Bosch",
            priority=0,
            source_url="https://example.com/wm-100",
        )

        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.status, "kept")
        self.assertEqual(stats["mapped"], 1)
        self.assertEqual(stats["already_filled"], 1)
        candidate = color.source_details["candidates"][0]
        self.assertEqual(candidate["raw_value"], "белый")
        self.assertEqual(candidate["value"], "Белый")
        self.assertEqual(candidate["url"], "https://example.com/wm-100")
        self.assertTrue(candidate["matches_current"])

    def test_donor_conflict_is_visible_without_overwriting_current_value(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            (
                '_MODEL_;_ATTRIBUTES_\r\n'
                'WM-100;"Основные|Цвет|Белый"\r\n'
            ).encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")

        service.apply_parsed_attributes(
            self.db,
            product,
            [{"name": "Цвет", "value": "Чёрный"}],
            source="Bosch",
            priority=0,
            source_url="https://example.com/wm-100",
        )

        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.status, "conflict")
        self.assertFalse(color.source_details["candidates"][0]["matches_current"])

        service.update_product_value(color, action="accept", manual_value="Чёрный")
        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Чёрный")
        self.assertEqual(color.status, "approved")

        service.update_product_value(color, action="reject")
        self.assertEqual(color.current_value, "Белый")
        self.assertEqual(color.final_value, "Белый")
        self.assertEqual(color.status, "rejected")
        self.assertEqual(color.proposed_value, "")

    def test_reject_without_current_value_keeps_explicit_rejected_status(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        color = next(value for value in batch.products[0].values if value.attribute_name == "Цвет")
        service.apply_candidate(
            batch.products[0],
            color,
            value="Белый",
            confidence=95,
            source="donor",
            reason="test",
            priority=0,
            source_name="Цвет",
        )

        service.update_product_value(color, action="reject")

        self.assertEqual(color.status, "rejected")
        self.assertEqual(color.final_value, "")
        self.assertEqual(color.proposed_value, "")
        self.assertEqual(batch.products[0].status, "needs_review")

    def test_source_comparison_uses_attribute_type_normalization(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            (
                '_MODEL_;_ATTRIBUTES_\r\n'
                'WM-100;"Размеры|Габариты|45,6 х 59.5 X 60"\r\n'
            ).encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        dimensions = next(
            value for value in product.values if value.attribute_name == "Габариты"
        )

        service.apply_parsed_attributes(
            self.db,
            product,
            [{"name": "Габариты", "value": "45.6X59,5 x 60"}],
            source="Bosch",
            priority=0,
            source_url="https://example.com/wm-100",
        )

        self.assertEqual(dimensions.status, "kept")
        self.assertTrue(dimensions.source_details["candidates"][0]["matches_current"])

    def test_imported_dash_is_preserved_as_a_technical_gap(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;"Основные|Цвет|-"\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        color = next(value for value in batch.products[0].values if value.attribute_name == "Цвет")
        self.assertEqual(color.current_value, "-")
        self.assertEqual(color.final_value, "-")
        self.assertEqual(color.status, "dash")

    def test_bulk_fill_dashes_normalizes_markers_and_changes_only_empty_gaps(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            (
                '_MODEL_;_ATTRIBUTES_\r\n'
                'WM-100;"Основные|Цвет|—"\r\n'
            ).encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        speed = next(
            value for value in product.values
            if value.attribute_name == "Максимальная скорость отжима об./мин."
        )

        self.assertEqual(color.current_value, "-")
        self.assertEqual(color.final_value, "-")
        self.assertEqual(speed.current_value, "")
        self.assertEqual(speed.final_value, "")
        self.assertFalse(any(item.value == "-" for item in color.template_field.allowed_values))

        changed = service.bulk_action(batch, "fill_dashes", dash_reason="Проверено")

        self.assertEqual(changed, len(template.fields) - 1)
        self.assertTrue(all(value.final_value == "-" for value in product.values if value.is_in_template))
        self.assertTrue(all(value.status == "dash" for value in product.values if value.is_in_template))
        self.assertEqual(product.status, "ready")

    def test_existing_dash_markers_are_migrated_without_touching_empty_values(self):
        from database.session import migrate_attribute_technical_dashes

        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        speed = next(
            value for value in product.values
            if value.attribute_name == "Максимальная скорость отжима об./мин."
        )
        color.current_value = "—"
        color.final_value = ""
        color.proposed_value = ""
        color.status = "missing"
        self.db.commit()

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE app_data_migrations ("
                    "name VARCHAR(255) NOT NULL PRIMARY KEY, details JSON NOT NULL DEFAULT '{}', "
                    "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            migrate_attribute_technical_dashes(connection)
            migrate_attribute_technical_dashes(connection)
        self.db.expire_all()

        self.assertEqual(color.current_value, "-")
        self.assertEqual(color.final_value, "-")
        self.assertEqual(color.proposed_value, "-")
        self.assertEqual(color.status, "dash")
        self.assertEqual(speed.current_value, "")
        self.assertEqual(speed.final_value, "")
        with self.engine.connect() as connection:
            migration_count = connection.execute(
                text("SELECT count(*) FROM app_data_migrations WHERE name = 'attribute_technical_dashes_v1'")
            ).scalar_one()
        self.assertEqual(migration_count, 1)

    def test_composite_template_keeps_ready_combination_and_components(self):
        template = self.make_template()
        programs = next(field for field in template.fields if field.name == "Список программ")
        values = {item.value: item.is_combination for item in programs.allowed_values}
        self.assertTrue(values["Быстрая/Хлопок"])
        self.assertFalse(values["Быстрая"])
        self.assertFalse(values["Хлопок"])
        canonical, confidence, _reason, _suggestions = service._allowed_match(programs, "Хлопок / Быстрая")
        self.assertEqual(canonical, "Быстрая/Хлопок")
        self.assertEqual(confidence, 100)

    def test_numeric_units_are_converted_only_for_matching_numeric_field(self):
        template = service.import_template_csv(
            self.db,
            "Мощность, Вт (Основные)\r\n1200\r\n".encode("cp1251"),
            name="Мощность",
            category="Тест > Мощность",
        )
        field = template.fields[0]
        canonical, confidence, reason, _suggestions = service._allowed_match(field, "1,2 кВт")
        self.assertEqual(canonical, "1200")
        self.assertGreaterEqual(confidence, 98)
        self.assertIn("Конвертация", reason)

    def test_processing_modes_have_distinct_auto_acceptance_policies(self):
        template = self.make_template()
        source = '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251")
        exact_batch = service.create_batch_from_csv(
            self.db, template, source, filename="exact.csv", processing_mode="auto_exact"
        )
        target = next(value for value in exact_batch.products[0].values if value.attribute_name == "Цвет")
        service.apply_candidate(
            exact_batch.products[0], target, value="Белый", confidence=99, source="donor",
            reason="test", priority=0, source_name="Цвет",
        )
        self.assertEqual(target.final_value, "")
        all_batch = service.create_batch_from_csv(
            self.db, template, source, filename="all.csv", processing_mode="auto_all"
        )
        target_all = next(value for value in all_batch.products[0].values if value.attribute_name == "Цвет")
        service.apply_candidate(
            all_batch.products[0], target_all, value="Белый", confidence=70, source="donor",
            reason="test", priority=0, source_name="Цвет",
        )
        self.assertEqual(target_all.final_value, "Белый")

    def test_template_preview_update_copy_and_restore(self):
        template = self.make_template()
        update = (
            "Цвет (Основные);Новый атрибут (Основные)\r\n"
            "Белый;Да\r\nСерый;Нет\r\n"
        ).encode("cp1251")
        preview = service.preview_template_csv(update, template)
        self.assertTrue(preview["can_import"])
        self.assertTrue(any(item["name"] == "Новый атрибут" for item in preview["fields"]))
        service.update_template_from_csv(self.db, template, update, mode="merge")
        self.assertTrue(any(field.name == "Новый атрибут" for field in template.fields))
        self.assertGreater(template.version, 1)
        copied = service.copy_template(self.db, template, name="Копия")
        self.assertEqual(len(copied.fields), len(template.fields))
        revision = template.revisions[0]
        service.restore_template_revision(self.db, template, revision)
        self.assertTrue(template.is_active)

    def test_donor_selector_adapter_reads_configured_rows(self):
        donor = Donor(
            brand=Brand(name="Selector donor", group_name="Test"),
            legacy_id="selector-adapter",
            site_url="https://example.com",
            selector_settings={
                "attribute_assistant": {
                    "attribute_row_selector": ".spec",
                    "attribute_name_selector": ".label",
                    "attribute_value_selector": ".data",
                }
            },
        )
        parsed = service.parse_product_html_for_donor(
            '<h1>WM</h1><div class="spec"><span class="label">Цвет</span><b class="data">Белый</b></div>',
            "https://example.com/wm",
            donor,
        )
        self.assertIn({"name": "Цвет", "value": "Белый", "group": ""}, parsed["attributes"])

    def test_donor_choice_and_manual_url_are_saved_per_product(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"), filename="products.csv"
        )
        donor = Donor(
            brand=Brand(name="Manual URL donor", group_name="Test"),
            legacy_id="manual-url",
            site_url="https://example.com",
        )
        self.db.add(donor)
        self.db.flush()
        with patch.object(service, "fetch_public_html", side_effect=ValueError("offline")):
            service.process_product_donors(
                self.db, batch.products[0], [donor.id], url_overrides={str(donor.id): "https://example.com/wm"}
            )
        self.assertEqual(batch.products[0].selected_donor_ids, [donor.id])
        self.assertEqual(batch.products[0].donor_url_overrides[str(donor.id)], "https://example.com/wm")

    def test_product_snapshot_can_restore_manual_decision(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"), filename="products.csv"
        )
        product = batch.products[0]
        color = next(value for value in product.values if value.attribute_name == "Цвет")
        snapshot = service.snapshot_product(self.db, product, "До изменения")
        service.update_product_value(color, action="accept", manual_value="Белый")
        self.assertEqual(color.final_value, "Белый")
        history = service.product_history(self.db, product)
        self.assertEqual(history[0]["changed_count"], 1)
        self.assertEqual(history[0]["changes"][0]["name"], "Цвет")
        self.assertEqual(history[0]["changes"][0]["before"], "—")
        self.assertEqual(history[0]["changes"][0]["after"], "Белый")
        service.restore_product_snapshot(self.db, product, snapshot)
        self.assertEqual(color.final_value, "")

    def test_url_import_keeps_success_and_error_rows_in_one_batch(self):
        template = self.make_template()
        calls = [
            ("<h1>WM-1</h1>", "https://example.com/wm-1"),
            ValueError("timeout"),
        ]
        with patch.object(service, "fetch_public_html", side_effect=calls):
            batch = service.create_batch_from_urls(
                self.db,
                ["https://example.com/wm-1", "https://example.com/wm-2"],
                template=template,
            )
        self.assertEqual(len(batch.products), 2)
        self.assertEqual(batch.source_urls[0]["status"], "parsed")
        self.assertEqual(batch.source_urls[1]["status"], "error")
    def test_batch_delete_removes_database_rows_and_all_owned_files(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        storage = Path(self.temp.name)
        raw_path = storage / "raw" / str(batch.id) / str(product.id) / "0_1.html"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text("<html>donor</html>", encoding="utf-8")
        source = AttributeProductSource(
            product=product,
            url="https://example.test/product",
            raw_html_path=str(raw_path),
        )
        revision = AttributeProductRevision(product=product, label="До удаления", snapshot={})
        self.db.add_all([source, revision])

        export_path = storage / "exports" / f"attributes_{batch.id}_current.csv"
        old_export_path = storage / "exports" / f"attributes_{batch.id}_old.csv"
        report_path = storage / "reports" / f"attribute_report_{batch.id}_current.csv"
        export_path.parent.mkdir(parents=True)
        report_path.parent.mkdir(parents=True)
        export_path.write_text("export", encoding="utf-8")
        old_export_path.write_text("old export", encoding="utf-8")
        report_path.write_text("report", encoding="utf-8")
        batch.export_path = str(export_path)
        batch.report_filename = str(report_path)
        self.db.flush()

        batch_id = batch.id
        product_id = product.id
        source_id = source.id
        revision_id = revision.id
        template_id = template.id
        original_path = Path(batch.original_path)

        deleted = service.delete_attribute_batch(self.db, batch)

        self.assertEqual(deleted["products"], 1)
        self.assertGreaterEqual(deleted["files"], 5)
        self.assertIsNone(self.db.get(AttributeBatch, batch_id))
        self.assertIsNone(self.db.get(AttributeProduct, product_id))
        self.assertIsNone(self.db.get(AttributeProductSource, source_id))
        self.assertIsNone(self.db.get(AttributeProductRevision, revision_id))
        self.assertIsNotNone(self.db.get(AttributeTemplate, template_id))
        for path in (original_path, export_path, old_export_path, report_path, raw_path):
            self.assertFalse(path.exists())

    def test_template_delete_is_explicit_and_blocked_while_used(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        self.db.flush()
        template_id = template.id
        field_id = template.fields[0].id
        allowed_id = template.fields[0].allowed_values[0].id

        with self.assertRaisesRegex(ValueError, "Шаблон используется"):
            service.delete_attribute_template(self.db, template)

        service.delete_attribute_batch(self.db, batch)
        service.delete_attribute_template(self.db, template)

        self.assertIsNone(self.db.get(AttributeTemplate, template_id))
        self.assertIsNone(self.db.get(AttributeTemplateField, field_id))
        self.assertIsNone(self.db.get(AttributeAllowedValue, allowed_id))

    def test_template_fields_can_be_created_and_deleted(self):
        template = self.make_template()
        field = service.create_template_field(
            self.db,
            template,
            group_name="Дополнительно",
            name="Новый атрибут",
            value_type="select",
        )
        self.assertEqual(field.sort_order, 4)
        service.delete_template_field(self.db, field)
        self.assertNotIn(field, template.fields)
        self.assertIsNone(self.db.get(type(field), field.id))

    def test_specific_shelf_rows_do_not_collapse_into_total_field(self):
        template = service.import_template_csv(
            self.db,
            (
                "Количество полок в холодильном отделении (Холодильное отделение)\r\n"
                "5\r\n"
            ).encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nKBN96ADD0;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        product = batch.products[0]
        stats = service.apply_parsed_attributes(
            self.db,
            product,
            [
                {"name": "Общее количество полок в холодильном отделении", "value": "5"},
                {"name": "Количество регулируемых полок в холодильном отделении", "value": "4"},
                {"name": "Количество фиксированных полок в холодильном отделении", "value": "1"},
            ],
            source="Bosch",
            priority=0,
        )
        target = product.values[0]
        self.assertEqual(stats["mapped"], 1)
        self.assertEqual(stats["ambiguous"], 2)
        self.assertEqual(target.proposed_value, "5")
        self.assertEqual(len(target.source_details.get("candidates") or []), 1)
        self.assertNotEqual(target.status, "conflict")

    def test_generic_cleanup_handles_labels_and_metric_units(self):
        template = service.import_template_csv(
            self.db,
            (
                "Класс энергоэффективности (Основные);Длина шнура, см (Размеры)\r\n"
                "D;230\r\n"
            ).encode("cp1251"),
            name="Техника",
            category="Техника",
        )
        energy, cable = template.fields
        self.assertEqual(service._allowed_match(energy, "D (старое обозначение класса)")[0], "D")
        self.assertEqual(service._allowed_match(cable, "2.3 м", "Длина шнура")[0], "230")

    def test_saved_donor_value_mapping_is_applied_before_fuzzy_matching(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        donor = Donor(
            brand=Brand(name="Test donor", group_name="Test"),
            legacy_id="value-mapping",
            site_url="https://example.com",
        )
        self.db.add(donor)
        self.db.flush()
        product = batch.products[0]
        first = service.apply_parsed_attributes(
            self.db,
            product,
            [{"name": "Цвет", "value": "Белоснежный"}],
            source="Test donor",
            priority=0,
            donor_id=donor.id,
        )
        self.assertEqual(first["unknown"], 1)
        field = template.fields[0]
        white = next(item for item in field.allowed_values if item.value == "Белый")
        service.save_value_mapping_rule(
            self.db,
            donor_id=donor.id,
            field=field,
            raw_value="Белоснежный",
            allowed_value_id=white.id,
        )
        second = service.apply_parsed_attributes(
            self.db,
            product,
            [{"name": "Цвет", "value": "Белоснежный"}],
            source="Test donor",
            priority=0,
            donor_id=donor.id,
        )
        target = next(item for item in product.values if item.template_field_id == field.id)
        self.assertEqual(second["mapped"], 1)
        self.assertEqual(target.proposed_value, "Белый")
        self.assertFalse(target.source_details.get("unknown_values"))

    def test_chatgpt_prompt_uses_relevant_allowed_value_shortlist(self):
        from services import attribute_ai

        template = service.import_template_csv(
            self.db,
            "Страна производства (Основные)\r\nГермания\r\n".encode("cp1251"),
            name="Холодильники",
            category="Холодильники",
        )
        field = template.fields[0]
        for index in range(120):
            service.add_allowed_value(self.db, field, f"Страна {index}")
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nKBN96ADD0;""\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        prompt, _evidence = attribute_ai.build_product_prompt(
            batch.products[0],
            source_url="https://example.com/product",
            html="<div>Страна производства: Германия</div>",
            parsed={"attributes": [{"name": "Страна производства", "value": "Германия"}]},
        )
        context = json.loads(prompt.split("КОНТЕКСТ ДЛЯ АНАЛИЗА:\n", 1)[1])
        prompt_field = context["template_fields"][0]
        self.assertEqual(prompt_field["allowed_values_total"], 121)
        self.assertLessEqual(len(prompt_field["allowed_values"]), 30)
        self.assertIn("Германия", prompt_field["allowed_values"])
        self.assertLess(len(prompt), 70_000)

    def _chatgpt_parallel_batch(self, count=4):
        from runtime import attribute_batch_operations as runtime

        template = self.make_template()
        csv = '_MODEL_;_ATTRIBUTES_\r\n' + ''.join(f'WM-{i};""\r\n' for i in range(count))
        batch = service.create_batch_from_csv(self.db, template, csv.encode("cp1251"), filename="products.csv")
        self.db.commit()
        runtime._JOBS[batch.id] = {
            "total": count, "prepared": 0, "processed": 0, "succeeded": 0, "failed": 0,
            "percent": 0, "changed": 0, "attributes_found": 0, "errors": [],
        }
        self.addCleanup(runtime._JOBS.pop, batch.id, None)
        return runtime, template, batch, [product.id for product in batch.products]

    def test_chatgpt_batch_runs_bounded_parallel_requests_and_saves_out_of_order(self):
        runtime, template, batch, product_ids = self._chatgpt_parallel_batch()
        coordinator = threading.get_ident()
        field_id = template.fields[0].id
        colors = {f"WM-{i}": "Белый" if i % 2 == 0 else "Чёрный" for i in range(4)}
        first_started = threading.Event()
        second_saved = threading.Event()
        preparation_barrier = threading.Barrier(2)
        lock = threading.Lock()
        active = 0
        max_active = 0
        active_preparations = 0
        max_active_preparations = 0
        saved = []
        fetcher = object()

        def db_session():
            return Session(self.engine, expire_on_commit=False)

        def prepare(db, product, donor_ids, **kwargs):
            nonlocal active_preparations, max_active_preparations
            self.assertNotEqual(threading.get_ident(), coordinator)
            self.assertIs(kwargs["fetcher"], fetcher)
            self.assertEqual(kwargs["url_overrides"], {"7": f"https://example.com/{product.model}"})
            with lock:
                active_preparations += 1
                max_active_preparations = max(max_active_preparations, active_preparations)
            try:
                preparation_barrier.wait(5)
                color = colors[product.model]
                return (f"https://example.com/{product.model}", f"<div>Цвет: {color}</div>",
                        {"attributes": [{"name": "Цвет", "value": color}]}, "test")
            finally:
                with lock:
                    active_preparations -= 1

        def analyze(prompt):
            nonlocal active, max_active
            self.assertNotEqual(threading.get_ident(), coordinator)
            context = json.loads(prompt.split("КОНТЕКСТ ДЛЯ АНАЛИЗА:\n", 1)[1])
            self.assertNotIn("products", context)
            model = context["product"]["model"]
            self.assertEqual(context["official_product_url"], f"https://example.com/{model}")
            self.assertEqual(
                context["parser_attributes"],
                [{"source_id": 1, "name": "Цвет", "value": colors[model]}],
            )
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                if model == "WM-0":
                    first_started.set()
                    self.assertTrue(second_saved.wait(5), "Second product was not saved while the first waited")
                elif model == "WM-1":
                    self.assertTrue(first_started.wait(5))
                return {"text": json.dumps({"attributes": [{
                    "source_id": 1, "field_id": field_id, "confidence": 80,
                }]})}
            finally:
                with lock:
                    active -= 1

        original_apply = runtime._apply_chatgpt_result

        def save(batch_id, prepared, future):
            self.assertEqual(threading.get_ident(), coordinator)
            self.assertTrue(future.done())
            original_apply(batch_id, prepared, future)
            saved.append(prepared["product_id"])
            if prepared["product_id"] == product_ids[1]:
                second_saved.set()

        overrides = {str(pid): {"7": f"https://example.com/WM-{i}"} for i, pid in enumerate(product_ids)}
        with patch.object(runtime, "CHATGPT_CONCURRENCY", 2), \
                patch.object(runtime, "SessionLocal", side_effect=db_session), \
                patch.object(runtime, "prepare_product_source", side_effect=prepare), \
                patch.object(runtime, "analyze_with_chatgpt", side_effect=analyze) as requests, \
                patch.object(runtime, "_apply_chatgpt_result", side_effect=save):
            runtime._run_chatgpt_products(batch.id, product_ids, [7], overrides, fetcher)
        self.assertEqual(requests.call_count, 4)
        self.assertEqual(max_active, 2)
        self.assertEqual(max_active_preparations, 2)
        self.assertEqual(saved[0], product_ids[1])
        state = runtime.get_attribute_batch_operation(batch.id)
        self.assertEqual((state["prepared"], state["processed"], state["succeeded"], state["failed"]), (4, 4, 4, 0))
        self.assertEqual(state["attributes_found"], 4)
        self.db.expire_all()
        for product_id in product_ids:
            product = self.db.get(AttributeProduct, product_id)
            color = next(value for value in product.values if value.attribute_name == "Цвет")
            self.assertEqual(color.proposed_value, colors[product.model])
            self.assertEqual(color.source_details["chatgpt"]["url"], f"https://example.com/{product.model}")
            self.assertEqual(color.source_details["chatgpt"]["evidence"], f"Цвет: {colors[product.model]}")

    def test_chatgpt_batch_continues_after_preparation_model_and_json_errors(self):
        runtime, template, batch, product_ids = self._chatgpt_parallel_batch(count=5)
        field_id = template.fields[0].id

        def prepare(db, product, donor_ids, **kwargs):
            if product.model == "WM-0":
                raise ValueError("Source unavailable")
            return (f"https://example.com/{product.model}", "<div>Цвет: Белый</div>",
                    {"attributes": [{"name": "Цвет", "value": "Белый"}]}, "test")

        def analyze(prompt):
            model = json.loads(prompt.split("КОНТЕКСТ ДЛЯ АНАЛИЗА:\n", 1)[1])["product"]["model"]
            if model == "WM-1":
                raise RuntimeError("Model failed")
            if model == "WM-2":
                return {"text": "invalid json"}
            return {"text": json.dumps({"attributes": [{
                "source_id": 1, "field_id": field_id, "confidence": 80,
            }]})}

        with patch.object(runtime, "CHATGPT_CONCURRENCY", 2), \
                patch.object(runtime, "SessionLocal", side_effect=lambda: Session(self.engine, expire_on_commit=False)), \
                patch.object(runtime, "prepare_product_source", side_effect=prepare), \
                patch.object(runtime, "analyze_with_chatgpt", side_effect=analyze) as requests:
            runtime._run_chatgpt_products(batch.id, product_ids, [], {}, object())
        self.assertEqual(requests.call_count, 4)
        state = runtime.get_attribute_batch_operation(batch.id)
        self.assertEqual((state["prepared"], state["processed"], state["succeeded"], state["failed"]), (4, 5, 2, 3))
        self.assertEqual({item["product_id"] for item in state["errors"]}, set(product_ids[:3]))
        self.assertEqual(state["changed"], 2)
        self.db.expire_all()
        for product_id in product_ids[3:]:
            product = self.db.get(AttributeProduct, product_id)
            self.assertEqual(next(value for value in product.values if value.attribute_name == "Цвет").proposed_value, "Белый")

    def test_chatgpt_batch_does_not_send_unprepared_products(self):
        runtime, template, batch, product_ids = self._chatgpt_parallel_batch(count=2)
        with patch.object(runtime, "SessionLocal", side_effect=lambda: Session(self.engine, expire_on_commit=False)), \
                patch.object(runtime, "prepare_product_source", side_effect=ValueError("No page")), \
                patch.object(runtime, "analyze_with_chatgpt") as requests:
            runtime._run_chatgpt_products(batch.id, product_ids, [], {}, object())
        requests.assert_not_called()
        state = runtime.get_attribute_batch_operation(batch.id)
        self.assertEqual((state["prepared"], state["processed"], state["failed"]), (0, 2, 2))

if __name__ == "__main__":
    unittest.main()
