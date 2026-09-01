import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
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
            "fetch_public_html",
            return_value=(html, "https://official.example.com/wm-100"),
        ):
            source_url, _html, _parsed, _reason = attribute_ai.prepare_product_source(
                self.db, product, [donor.id]
            )
        prompt, _evidence = attribute_ai.build_product_prompt(product, source_url=source_url, html=html)
        self.assertEqual(source_url, "https://official.example.com/wm-100")
        self.assertIn('"official_product_url":"https://official.example.com/wm-100"', prompt)

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
        self.assertEqual(context["parser_attributes"], [{"name": "Цвет", "value": "Белый"}])

        analysis = attribute_ai.validate_analysis(
            product,
            {
                "observed_attributes": [
                    {"name": "Цвет", "value": "Белый", "evidence": "Цвет: Белый"}
                ],
                "suggestions": [
                    {
                        "template_field_id": color.template_field_id,
                        "proposed_value": "Белый",
                        "confidence": 82,
                        "explanation": "Значение подтверждено страницей",
                        "evidence": "Цвет: Белый",
                    }
                ],
                "warnings": [],
            },
            page_evidence=evidence,
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
                "suggestions": [
                    {
                        "template_field_id": color.template_field_id,
                        "proposed_value": "Чёрный",
                        "confidence": 80,
                        "explanation": "На странице указано другое значение",
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

        with patch.object(attribute_ai, "fetch_public_html") as fetch:
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
            "fetch_public_html",
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
            "product": {"name": "Машина", "model": "WM-100", "brand": "", "category": ""},
            "observed_attributes": [
                {"name": "Цвет", "value": "Белый", "evidence": "Цвет: Белый"}
            ],
            "suggestions": [
                {
                    "template_field_id": color.template_field_id,
                    "proposed_value": "Белый",
                    "confidence": 82,
                    "explanation": "Указано на странице",
                    "evidence": "Цвет: Белый",
                },
                {
                    "template_field_id": color.template_field_id,
                    "proposed_value": "Серый",
                    "confidence": 80,
                    "explanation": "Недопустимое значение",
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
        self.assertEqual(color.status, "kept")

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

    def test_imported_dash_is_a_missing_value_not_an_approved_final(self):
        template = self.make_template()
        batch = service.create_batch_from_csv(
            self.db,
            template,
            '_MODEL_;_ATTRIBUTES_\r\nWM-100;"Основные|Цвет|-"\r\n'.encode("cp1251"),
            filename="products.csv",
        )
        color = next(value for value in batch.products[0].values if value.attribute_name == "Цвет")
        self.assertEqual(color.current_value, "-")
        self.assertEqual(color.final_value, "")
        self.assertEqual(color.status, "missing")

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

if __name__ == "__main__":
    unittest.main()
