import csv
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from services.attribute_assistant import (
    _decode_html_content,
    AttributeProductPageLoader,
    add_value_synonym,
    allowed_value_field_ids,
    batch_report,
    bulk_update_values,
    create_allowed_value,
    detect_template_for_page,
    export_batch_csv,
    export_batch_report_csv,
    field_allowed_values,
    import_products_csv,
    import_products_from_urls,
    import_template_csv,
    list_template_revisions,
    load_product,
    normalize_attribute_value,
    parse_attributes_block,
    parse_product_page,
    parse_donor_for_product,
    parse_template_header,
    preview_template_csv,
    public_product,
    restore_template_revision,
    save_attribute_donor,
    save_mapping_rule,
    update_product_value,
    workspace_payload,
)
from services.attribute_ai import (
    apply_attribute_suggestions,
    attribute_analysis_needs_web_fallback,
    build_attribute_analysis_prompt,
    build_attribute_url_analysis_prompt,
    validate_attribute_analysis,
)


class AttributeAssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.temporary = TemporaryDirectory()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary.cleanup()

    @staticmethod
    def template_csv() -> bytes:
        return (
            "Тип установки (Общие параметры);"
            "Габариты, см (ШхВхГ) (Габариты и вес);"
            "Основной цвет (Общие параметры)\r\n"
            "Встраиваемый;84,7 х 59,6 х 66;Белый\r\n"
            "Отдельностоящий;;Черный\r\n"
        ).encode("cp1251")

    @staticmethod
    def products_csv() -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        writer.writerow(["_ID_", "_NAME_", "_MODEL_", "_ATTRIBUTES_"])
        writer.writerow(
            [
                "123",
                "Стиральная машина AEG",
                "LFR85166SOE",
                (
                    "Общие параметры|Тип установки|Встраиваемый\n"
                    "Общие параметры|Основной цвет|-\n"
                    "Пользовательские|Мощность|8000"
                ),
            ]
        )
        return output.getvalue().encode("cp1251")

    def import_fixture(self, session, *, processing_mode: str = "suggest"):
        template, report = import_template_csv(
            session,
            self.template_csv(),
            category_name="Стиральные машины",
            category_path="Бытовая техника → Стиральные машины",
            template_name="Стиральные машины",
        )
        batch = import_products_csv(
            session,
            template,
            self.products_csv(),
            source_filename="products.csv",
            stored_filename="stored.csv",
            processing_mode=processing_mode,
        )
        session.flush()
        return template, batch, report

    def test_last_parentheses_define_template_group(self) -> None:
        name, group = parse_template_header(
            "Габариты, см (ШхВхГ) (Габариты и вес)"
        )
        self.assertEqual(name, "Габариты, см (ШхВхГ)")
        self.assertEqual(group, "Габариты и вес")

    def test_attributes_block_preserves_value_delimiters(self) -> None:
        parsed = parse_attributes_block(
            "Общие|Комплектация|полка|контейнер\nОбщие|Ширина, см|84.7"
        )
        self.assertEqual(
            parsed,
            [
                ("Общие", "Комплектация", "полка|контейнер"),
                ("Общие", "Ширина, см", "84.7"),
            ],
        )

    def test_normalization_follows_template_types(self) -> None:
        self.assertEqual(normalize_attribute_value("84,7", "number"), "84.7")
        self.assertEqual(
            normalize_attribute_value("84,7 х 59,6 Х 66", "dimensions"),
            "84.7 x 59.6 x 66",
        )
        self.assertEqual(
            normalize_attribute_value("Гриль / Конвекция / Гриль", "composite"),
            "Гриль/Конвекция",
        )

    def test_template_preview_update_and_revision_history(self) -> None:
        with self.Session.begin() as session:
            preview = preview_template_csv(
                session,
                self.template_csv(),
                category_name="Стиральные машины",
                category_path="Бытовая техника → Стиральные машины",
                template_name="Стиральные машины",
            )
            self.assertFalse(preview["template_exists"])
            self.assertEqual(preview["fields_count"], 3)

            template, report = import_template_csv(
                session,
                self.template_csv(),
                category_name="Стиральные машины",
                category_path="Бытовая техника → Стиральные машины",
                template_name="Стиральные машины",
            )
            self.assertEqual(report["new_fields"], 3)
            template_id = template.id

            updated, update_report = import_template_csv(
                session,
                "Основной цвет (Общие параметры)\r\nБелый\r\nСерый\r\n".encode("cp1251"),
                category_name="Стиральные машины",
                category_path="Бытовая техника → Стиральные машины",
                template_name="Стиральные машины",
                mode="replace",
            )
            self.assertEqual(updated.id, template_id)
            self.assertEqual([field.name for field in updated.fields], ["Основной цвет"])
            self.assertGreaterEqual(update_report["new_values"], 2)
            revisions = list_template_revisions(session, template_id)
            self.assertGreaterEqual(len(revisions), 2)

            created_revision = next(item for item in revisions if item["action"] == "created")
            restored = restore_template_revision(session, updated, created_revision["id"])
            self.assertEqual(
                [field.name for field in restored.fields],
                ["Тип установки", "Габариты, см (ШхВхГ)", "Основной цвет"],
            )

    def test_global_value_is_reused_by_same_attribute_in_another_template(self) -> None:
        with self.Session.begin() as session:
            first, _ = import_template_csv(
                session,
                "Основной цвет (Общие)\r\nБелый\r\n".encode("cp1251"),
                category_name="Первая категория",
                category_path="Каталог → Первая категория",
                template_name="Первый шаблон",
            )
            first.fields[0].allowed_values[0].is_global = True

            second, _ = import_template_csv(
                session,
                "Основной цвет (Общие)\r\nСерый\r\n".encode("cp1251"),
                category_name="Вторая категория",
                category_path="Каталог → Вторая категория",
                template_name="Второй шаблон",
            )
            products = (
                '_MODEL_;_ATTRIBUTES_\r\nTEST-2;"Общие|Основной цвет|Белый"\r\n'
            ).encode("cp1251")
            batch = import_products_csv(
                session,
                second,
                products,
                source_filename="second.csv",
                stored_filename="second.csv",
            )
            color = batch.products[0].values[0]
            self.assertEqual(color.final_value, "Белый")
            self.assertEqual(color.status, "filled")
            dictionary = field_allowed_values(session, second.fields[0].id)
            self.assertEqual(
                {item["value"] for item in dictionary["allowed_values"]},
                {"Белый", "Серый"},
            )

    def test_safe_unit_conversions_match_existing_dictionary_values(self) -> None:
        with self.Session.begin() as session:
            template, _ = import_template_csv(
                session,
                (
                    "Мощность, Вт (Потребление);Гарантия (Заводские данные)\r\n"
                    "3100;1 год\r\n"
                ).encode("cp1251"),
                category_name="Техника",
                category_path="Каталог → Техника",
                template_name="Техника",
            )
            products = (
                '_MODEL_;_ATTRIBUTES_\r\nTEST-3;"Потребление|Мощность, Вт|3.1 кВт\n'
                'Заводские данные|Гарантия|12 месяцев"\r\n'
            ).encode("cp1251")
            batch = import_products_csv(
                session,
                template,
                products,
                source_filename="units.csv",
                stored_filename="units.csv",
            )
            values = {item.attribute_name: item.final_value for item in batch.products[0].values}
            self.assertEqual(values["Мощность, Вт"], "3100")
            self.assertEqual(values["Гарантия"], "1 год")

    def test_similar_products_suggest_only_safe_non_numeric_values(self) -> None:
        with self.Session.begin() as session:
            template, _ = import_template_csv(
                session,
                "Основной цвет (Общие)\r\nБелый\r\nЧерный\r\n".encode("cp1251"),
                category_name="Стиральные машины",
                category_path="Каталог → Стиральные машины",
                template_name="Стиральные машины",
            )
            first = (
                '_NAME_;_MODEL_;_ATTRIBUTES_\r\n'
                '"Стиральная машина AEG";LFR85166;"Общие|Основной цвет|Белый"\r\n'
            ).encode("cp1251")
            import_products_csv(
                session,
                template,
                first,
                source_filename="first.csv",
                stored_filename="first.csv",
            )
            second = (
                '_NAME_;_MODEL_;_ATTRIBUTES_\r\n'
                '"Стиральная машина AEG";LFR85167;""\r\n'
            ).encode("cp1251")
            batch = import_products_csv(
                session,
                template,
                second,
                source_filename="second.csv",
                stored_filename="second.csv",
                processing_mode="suggest",
            )
            value = batch.products[0].values[0]
            self.assertEqual(value.proposed_value, "Белый")
            self.assertEqual(value.source, "similar_products")
            self.assertEqual(value.status, "proposed")

    def test_dictionary_synonym_and_lazy_payload(self) -> None:
        with self.Session.begin() as session:
            template, batch, _report = self.import_fixture(session)
            field = next(item for item in template.fields if item.name == "Основной цвет")
            white = next(item for item in field.allowed_values if item.value == "Белый")
            synonym = add_value_synonym(session, white, "white")
            self.assertEqual(synonym.normalized_synonym, "white")
            created = create_allowed_value(
                session,
                field,
                {"value": "Серый", "is_global": True, "is_recommended": True},
            )
            self.assertTrue(created.is_global)

            product = load_product(session, batch.products[0].id, include_allowed_values=False)
            field_ids = allowed_value_field_ids(
                session,
                (item.template_field_id for item in product.values),
            )
            payload = public_product(product, allowed_fields=field_ids)
            color_payload = next(item for item in payload["values"] if item["attribute_name"] == "Основной цвет")
            dictionary = field_allowed_values(session, color_payload["template_field_id"])
            self.assertEqual(color_payload["allowed_values"], [])
            self.assertIn("Серый", [item["value"] for item in dictionary["allowed_values"]])

    def test_import_keeps_full_stack_and_rejects_unknown_dictionary_value(self) -> None:
        with self.Session.begin() as session:
            _template, batch, report = self.import_fixture(session)
            self.assertEqual(report["new_fields"], 3)
            product = load_product(session, batch.products[0].id)
            values = {item.attribute_name: item for item in product.values}
            self.assertEqual(values["Тип установки"].final_value, "Встраиваемый")
            self.assertEqual(values["Мощность"].status, "extra")
            self.assertEqual(values["Основной цвет"].status, "dash")

            with self.assertRaisesRegex(ValueError, "отсутствует в справочнике"):
                update_product_value(session, product, values["Основной цвет"].id, "Фиолетовый")
            update_product_value(session, product, values["Основной цвет"].id, "Белый")
            self.assertEqual(values["Основной цвет"].status, "accepted")

    def test_bulk_action_report_and_cp1251_export(self) -> None:
        with self.Session.begin() as session:
            _template, batch, _report = self.import_fixture(session)
            result = bulk_update_values(session, batch, action="dash")
            self.assertGreater(result["changed"], 0)
            report = batch_report(session, batch)
            self.assertEqual(report["batch"]["products_count"], 1)
            self.assertIn("summary", report)

            with patch(
                "services.attribute_assistant.ATTRIBUTE_ASSISTANT_DIR",
                Path(self.temporary.name),
            ):
                export_path = export_batch_csv(session, batch)
                report_path = export_batch_report_csv(session, batch)
                exported = export_path.read_bytes().decode("cp1251")
                report_text = report_path.read_bytes().decode("cp1251")

        rows = list(csv.reader(io.StringIO(exported), delimiter=";"))
        self.assertEqual(rows[0], ["_MODEL_", "_ATTRIBUTES_"])
        self.assertEqual(rows[1][0], "LFR85166SOE")
        self.assertIn("Пользовательские|Мощность|8000", rows[1][1])
        self.assertIn("Модель", report_text)

    def test_generic_product_page_parser_reads_json_ld_and_table(self) -> None:
        html = """
        <html><head><script type="application/ld+json">
        {"@type":"Product","name":"Холодильник AEG","sku":"RKB638E4MX","brand":{"name":"AEG"}}
        </script></head><body>
        <table><tr><th>Цвет</th><td>Нержавеющая сталь</td></tr></table>
        <dl><dt>Ширина, см</dt><dd>59,5</dd></dl>
        </body></html>
        """
        parsed = parse_product_page(html, "https://example.com/product")
        self.assertEqual(parsed["model"], "RKB638E4MX")
        self.assertEqual(parsed["brand"], "AEG")
        self.assertIn(
            {"group_name": "Характеристики", "name": "Цвет", "value": "Нержавеющая сталь"},
            parsed["attributes"],
        )
        self.assertIn(
            {"group_name": "Характеристики", "name": "Ширина, см", "value": "59,5"},
            parsed["attributes"],
        )

    def test_html_decoder_does_not_override_explicit_utf8_with_detector_guess(self) -> None:
        content = "Холодильник — характеристики".encode("utf-8")

        decoded = _decode_html_content(
            content,
            content_type="text/html; charset=utf-8",
            apparent_encoding="MacRoman",
        )

        self.assertEqual(decoded, "Холодильник — характеристики")

    def test_generic_product_page_parser_reads_semantic_div_rows_and_metadata(self) -> None:
        html = """
        <html><head>
          <meta property="og:title" content="Холодильник Acme ABC-123">
          <meta name="description" content="Описание товара">
        </head><body>
          <nav class="catalog-breadcrumbs"><a>Главная</a><a>Холодильники</a></nav>
          <section class="product-characteristics">
            <div class="catalog-char-row"><div class="title">Объем, л</div><div class="value">334</div></div>
            <div class="specification-row"><span class="spec-name">Цвет</span><span class="spec-value">Белый</span></div>
          </section>
        </body></html>
        """

        parsed = parse_product_page(html, "https://example.com/product/acme-abc-123")

        self.assertEqual(parsed["name"], "Холодильник Acme ABC-123")
        self.assertEqual(parsed["model"], "ABC-123")
        self.assertEqual(parsed["description"], "Описание товара")
        self.assertEqual(parsed["category"], "Холодильники")
        self.assertIn(
            {"group_name": "Характеристики", "name": "Объем, л", "value": "334"},
            parsed["attributes"],
        )
        self.assertIn(
            {"group_name": "Характеристики", "name": "Цвет", "value": "Белый"},
            parsed["attributes"],
        )

    def test_generic_product_page_parser_reads_json_ld_additional_properties(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Духовой шкаф TEST-42",
          "additionalProperty": [
            {"@type": "PropertyValue", "name": "Мощность", "value": "3,5 кВт"}
          ]
        }
        </script>
        """

        parsed = parse_product_page(html, "https://example.com/test-42")

        self.assertIn(
            {"group_name": "Характеристики", "name": "Мощность", "value": "3,5 кВт"},
            parsed["attributes"],
        )

    def test_generic_product_page_parser_reads_name_val_list_rows(self) -> None:
        html = """
        <section class="product-features">
          <ul>
            <li><span class="name">Полезный объем, л</span><span class="val">331</span></li>
            <li><span class="name">Тип компрессора</span><span class="val">Инверторный</span></li>
          </ul>
        </section>
        """

        parsed = parse_product_page(html, "https://example.com/product/test-42")

        self.assertIn(
            {"group_name": "Характеристики", "name": "Полезный объем, л", "value": "331"},
            parsed["attributes"],
        )
        self.assertIn(
            {"group_name": "Характеристики", "name": "Тип компрессора", "value": "Инверторный"},
            parsed["attributes"],
        )

    def test_product_page_loader_renders_javascript_shell_only_as_fallback(self) -> None:
        rendered_html = """
        <h1>Холодильник Acme ABC-123</h1>
        <section class="product-specs">
          <div class="spec-row"><span class="name">Цвет</span><span class="value">Белый</span></div>
        </section>
        """
        loader = AttributeProductPageLoader()
        with (
            patch(
                "services.attribute_assistant.fetch_product_html",
                return_value=("https://example.com/product/abc-123", "<html><app-root></app-root></html>"),
            ),
            patch.object(loader, "_render", return_value=rendered_html) as render,
        ):
            _url, html, parsed = loader.load("https://example.com/product/abc-123")

        self.assertEqual(html, rendered_html)
        self.assertEqual(parsed["model"], "ABC-123")
        self.assertEqual(len(parsed["attributes"]), 1)
        render.assert_called_once()

    def test_workspace_and_saved_donor_mapping_are_serializable(self) -> None:
        with self.Session.begin() as session:
            template, _batch, _report = self.import_fixture(session)
            donor = save_attribute_donor(
                session,
                {
                    "name": "Официальный сайт",
                    "domain": "example.com",
                    "base_url": "https://example.com",
                    "selectors": {"model_selector": ".sku"},
                },
            )
            rule = save_mapping_rule(
                session,
                donor=donor,
                template=template,
                donor_attribute_name="Цвет корпуса",
                field=next(field for field in template.fields if field.name == "Основной цвет"),
            )
            payload = workspace_payload(session)
            self.assertEqual(payload["metrics"]["products"], 1)
            self.assertEqual(payload["donors"][0]["mapping_rules"][0]["id"], rule.id)

    def test_url_mode_can_detect_template_from_breadcrumbs(self) -> None:
        with self.Session.begin() as session:
            template, _ = import_template_csv(
                session,
                "Основной цвет (Общие)\r\nБелый\r\n".encode("cp1251"),
                category_name="Стиральные машины",
                category_path="Бытовая техника → Стиральные машины",
                template_name="Стиральные машины",
                is_default=True,
            )
            parsed = {
                "category": "Стиральные машины",
                "breadcrumbs": ["Главная", "Бытовая техника", "Стиральные машины"],
            }
            self.assertEqual(detect_template_for_page(session, parsed).id, template.id)

            html = """
            <html><head><script type="application/ld+json">
            {"@type":"Product","name":"Стиральная машина","sku":"TEST-URL"}
            </script></head><body>
            <nav class="breadcrumb"><a>Главная</a><a>Бытовая техника</a><a>Стиральные машины</a></nav>
            <table><tr><th>Основной цвет</th><td>Белый</td></tr></table>
            </body></html>
            """
            with patch(
                "services.attribute_assistant.fetch_product_html",
                return_value=("https://example.com/test", html),
            ):
                batch = import_products_from_urls(
                    session,
                    None,
                    ["https://example.com/test"],
                )
            self.assertEqual(batch.template_id, template.id)
            self.assertEqual(batch.products[0].model, "TEST-URL")

    def test_multiple_donors_create_a_visible_conflict_and_keep_raw_html(self) -> None:
        with self.Session.begin() as session:
            template, _ = import_template_csv(
                session,
                "Основной цвет (Характеристики)\r\nБелый\r\nЧерный\r\n".encode("cp1251"),
                category_name="Техника",
                category_path="Каталог → Техника",
                template_name="Техника",
            )
            products = '_MODEL_;_ATTRIBUTES_\r\nTEST-DONOR;""\r\n'.encode("cp1251")
            batch = import_products_csv(
                session,
                template,
                products,
                source_filename="donor.csv",
                stored_filename="donor.csv",
            )
            product = load_product(session, batch.products[0].id)
            white_html = "<table><tr><th>Основной цвет</th><td>Белый</td></tr></table>"
            black_html = "<table><tr><th>Основной цвет</th><td>Черный</td></tr></table>"
            with (
                patch("services.attribute_assistant.ATTRIBUTE_ASSISTANT_DIR", Path(self.temporary.name)),
                patch(
                    "services.attribute_assistant.fetch_product_html",
                    side_effect=[
                        ("https://one.example/product", white_html),
                        ("https://two.example/product", black_html),
                    ],
                ),
            ):
                first = parse_donor_for_product(
                    session,
                    product,
                    url="https://one.example/product",
                    priority=0,
                )
                parse_donor_for_product(
                    session,
                    product,
                    url="https://two.example/product",
                    priority=1,
                )
                self.assertTrue((Path(self.temporary.name) / "donor-html" / first.raw_html_path).is_file())
            value = product.values[0]
            self.assertEqual(value.status, "conflict")
            self.assertEqual(len(value.source_details["candidates"]), 2)


    def test_attribute_ai_prompt_and_validation_use_allowed_values(self) -> None:
        with self.Session.begin() as session:
            template, _batch, _report = self.import_fixture(session)
            field = next(item for item in template.fields if item.name == "Основной цвет")
            output = {
                "product": {"name": "Товар", "model": "TEST", "brand": "", "category": ""},
                "observed_attributes": [
                    {"name": "Основной цвет", "value": "Белый", "evidence": "Основной цвет: Белый"}
                ],
                "suggestions": [
                    {
                        "template_field_id": field.id,
                        "proposed_value": "Белый",
                        "confidence": 85,
                        "explanation": "Значение прямо указано на странице",
                        "evidence": "Основной цвет: Белый",
                    }
                ],
                "warnings": [],
            }
            parsed = {
                "url": "https://example.test/product",
                "name": "Товар TEST",
                "model": "TEST",
                "brand": "",
                "category": "",
                "attributes": [
                    {"group_name": "Общие параметры", "name": "Основной цвет", "value": "Белый"}
                ],
            }
            prepared = build_attribute_analysis_prompt(
                session,
                html="<div>Основной цвет: Белый</div>",
                parsed=parsed,
                template=template,
                current_values={field.id: "-"},
            )
            self.assertIn("Верни только один валидный JSON-объект", prepared["prompt"])
            self.assertIn(f'"id": {field.id}', prepared["prompt"])
            self.assertIn('"current_value": ""', prepared["prompt"])
            self.assertIn("Основной цвет: Белый", prepared["prompt"])
            analysis = validate_attribute_analysis(
                session,
                response=f"```json\n{json.dumps(output, ensure_ascii=False)}\n```",
                page_evidence=prepared["validation_context"]["page_evidence"],
                template=template,
            )
            self.assertEqual(analysis["suggestions"][0]["proposed_value"], "Белый")
            self.assertEqual(analysis["observed_attributes"][0]["value"], "Белый")

    def test_attribute_ai_url_prompt_does_not_require_local_parser_output(self) -> None:
        with self.Session.begin() as session:
            template, _batch, _report = self.import_fixture(session)
            field = next(item for item in template.fields if item.name == "Основной цвет")
            prepared = build_attribute_url_analysis_prompt(
                session,
                source_url="https://example.test/product",
                template=template,
                current_values={field.id: "-"},
            )

            self.assertIn('"source_url": "https://example.test/product"', prepared["prompt"])
            self.assertIn('"source_host": "example.test"', prepared["prompt"])
            self.assertIn('"web_access_mode": "direct_then_same_domain_search"', prepared["prompt"])
            self.assertIn("site:source_host", prepared["prompt"])
            self.assertNotIn("ДАННЫЕ, НАЙДЕННЫЕ ПАРСЕРОМ", prepared["prompt"])
            self.assertEqual(prepared["validation_context"]["page_evidence"], "")

            fallback = build_attribute_url_analysis_prompt(
                session,
                source_url="https://example.test/product",
                template=template,
                current_values={field.id: "-"},
                same_domain_fallback=True,
            )
            self.assertIn('"web_access_mode": "same_domain_search_after_timeout"', fallback["prompt"])
            self.assertIn("Не вызывай openPage", fallback["prompt"])

            analysis = validate_attribute_analysis(
                session,
                response={
                    "product": {"name": "Товар", "model": "TEST", "brand": "", "category": ""},
                    "observed_attributes": [
                        {"name": "Основной цвет", "value": "Белый", "evidence": "Основной цвет — Белый"}
                    ],
                    "suggestions": [
                        {
                            "template_field_id": field.id,
                            "proposed_value": "Белый",
                            "confidence": 85,
                            "explanation": "Указано на странице",
                            "evidence": "Основной цвет — Белый",
                        }
                    ],
                    "warnings": [],
                },
                template=template,
            )
            self.assertEqual(analysis["suggestions"][0]["proposed_value"], "Белый")

    def test_attribute_ai_retries_only_empty_source_access_failures(self) -> None:
        timed_out = {
            "product": {"name": "", "model": "", "brand": "", "category": ""},
            "observed_attributes": [],
            "suggestions": [],
            "warnings": [
                "Не удалось открыть указанную страницу: источник дважды вернул ошибку тайм-аута."
            ],
        }
        self.assertTrue(attribute_analysis_needs_web_fallback(timed_out))

        with_evidence = dict(timed_out)
        with_evidence["observed_attributes"] = [
            {"name": "Цвет", "value": "Белый", "evidence": "Цвет: Белый"}
        ]
        self.assertFalse(attribute_analysis_needs_web_fallback(with_evidence))

        no_attributes = dict(timed_out)
        no_attributes["warnings"] = ["На странице нет таблицы характеристик"]
        self.assertFalse(attribute_analysis_needs_web_fallback(no_attributes))

    def test_attribute_ai_suggestion_is_reviewable_and_does_not_overwrite_current_value(self) -> None:
        with self.Session.begin() as session:
            template, batch, _report = self.import_fixture(session)
            product = load_product(session, batch.products[0].id)
            field = next(item for item in template.fields if item.name == "Основной цвет")
            analysis = {
                "prompt_version": "test",
                "observed_attributes": [{"name": "Основной цвет", "value": "Белый", "evidence": "Белый"}],
                "suggestions": [
                    {
                        "template_field_id": field.id,
                        "proposed_value": "Белый",
                        "confidence": 85,
                        "explanation": "Указано на странице",
                        "evidence": "Белый",
                    }
                ],
            }
            changed = apply_attribute_suggestions(
                session,
                product,
                analysis,
                source_url="https://example.test/product",
            )
            value = next(item for item in product.values if item.template_field_id == field.id)
            self.assertEqual(changed, 1)
            self.assertEqual(value.proposed_value, "Белый")
            self.assertEqual(value.source, "chatgpt")
            self.assertEqual(value.status, "proposed")
            self.assertEqual(value.final_value, "-")

            value.proposed_value = "Белый"
            value.source = "primary_donor"
            value.confidence = 90
            apply_attribute_suggestions(
                session,
                product,
                analysis,
                source_url="https://example.test/product",
            )
            self.assertEqual(value.source, "primary_donor")
            self.assertEqual(value.confidence, 90)

            value.current_value = "Черный"
            value.proposed_value = ""
            value.source = "current"
            changed = apply_attribute_suggestions(
                session,
                product,
                analysis,
                source_url="https://example.test/product",
            )
            self.assertEqual(changed, 0)
            self.assertEqual(value.current_value, "Черный")
            self.assertEqual(value.proposed_value, "")


if __name__ == "__main__":
    unittest.main()
