"""Regression coverage for punctuation-sensitive OpenCart dictionaries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, Brand, Donor
from services import attribute_assistant as svc
from services import attribute_ai as ai


class ExactDictionaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "dictionary.db"))
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.storage_patch = patch.object(svc, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name))
        self.storage_patch.start()
        self.template = svc.import_template_csv(
            self.db, "Класс (Основные)\nA\n".encode("utf-8"),
            name="Техника", category="Техника",
        )
        self.field = self.template.fields[0]
        self.assertEqual(self.field.value_type, "select")
        for value in ["A+", "A++", "60/65", "60-65", "60 65"]:
            svc.add_allowed_value(self.db, self.field, value)
        self.db.commit()

    def tearDown(self):
        self.storage_patch.stop()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def product(self, current=""):
        stack = "Основные|Класс|" + current if current else ""
        batch = svc.create_batch_from_csv(
            self.db, self.template,
            ('_MODEL_;_ATTRIBUTES_\nTEST;"' + stack + '"\n').encode("utf-8"),
            filename="products.csv",
        )
        self.db.flush()
        return batch.products[0]


    def test_csv_import_automatically_preserves_distinct_classes(self):
        template = svc.import_template_csv(
            self.db, "Класс (Основные)\nA\nA+\nA++\n".encode("utf-8"),
            name="CSV", category="CSV",
        )
        field = template.fields[0]
        self.assertEqual(field.value_type, "select")
        self.assertEqual([v.value for v in field.allowed_values], ["A", "A+", "A++"])

    def test_csv_merge_with_existing_value_detects_new_punctuation_variant(self):
        template = svc.import_template_csv(
            self.db, "Класс (Основные)\nB\n".encode("utf-8"), name="Old CSV", category="Old CSV",
        )
        payload = "Класс (Основные)\nB++\n".encode("utf-8")
        svc.update_template_from_csv(self.db, template, payload)
        self.assertEqual(template.fields[0].value_type, "select")
        self.assertEqual([v.value for v in template.fields[0].allowed_values], ["B", "B++"])



    def test_every_character_distinguishes_dictionary_values(self):
        variants = ["a", "А", "Е", "е", "Ё", "ё", "A B", "A  B", "AB", "A/B", "A-B", "A.B", "A,B"]
        for value in variants:
            svc.add_allowed_value(self.db, self.field, value)
        self.db.flush()
        self.assertEqual(len({v.normalized_value for v in self.field.allowed_values}), 6 + len(variants))
        for value in variants:
            self.assertEqual(svc._allowed_match(self.field, value)[0], value)
        for value in ["A\\B", "A_B", "A(B)"]:
            self.assertEqual(svc._allowed_match(self.field, value)[0], "")

    def test_plain_csv_keeps_slashes_and_inner_spaces(self):
        template = svc.import_template_csv(
            self.db, "Размер (Основные)\n60/65\n60-65\nA B\nA  B\n".encode("utf-8"),
            name="Literal CSV", category="Literal CSV",
        )
        field = template.fields[0]
        self.assertFalse(field.is_composite)
        self.assertEqual([v.value for v in field.allowed_values], ["60/65", "60-65", "A B", "A  B"])
        batch = svc.create_batch_from_csv(
            self.db, template, '_MODEL_;_ATTRIBUTES_\nP;"Основные|Размер|A  B"\n'.encode("utf-8"),
            filename="products.csv",
        )
        self.assertEqual(batch.products[0].values[0].final_value, "A  B")

    def test_numbers_keep_sign_and_decimal_point(self):
        template = svc.import_template_csv(
            self.db, "Число (Основные)\n-5\n5\n5.1\n51\n".encode("utf-8"),
            name="Numbers", category="Numbers",
        )
        field = template.fields[0]
        self.assertEqual([v.normalized_value for v in field.allowed_values], ["-5", "5", "5.1", "51"])
        for value in ["-5", "5", "5.1", "51"]:
            self.assertEqual(svc._allowed_match(field, value)[0], value)
        self.assertEqual(svc._allowed_match(field, "5.2")[0], "")

    def test_migration_preserves_ids_links_and_handles_old_key_collisions(self):
        from sqlalchemy import text
        from database.session import migrate_attribute_value_keys
        allowed = self.field.allowed_values[0]
        plus = self.field.allowed_values[1]
        svc.replace_allowed_value_synonyms(self.db, plus, ["Класс A+"])
        donor = Donor(brand=Brand(name="Migration"), site_url="https://example.com")
        self.db.add(donor)
        self.db.flush()
        rule = svc.save_value_mapping_rule(
            self.db, donor_id=donor.id, field=self.field, raw_value="Класс A+",
            allowed_value_id=plus.id,
        )
        self.db.commit()
        allowed.normalized_value = "old_A"
        self.db.flush()
        plus.normalized_value = "A"
        plus.synonyms[0].normalized_synonym = "класс a"
        rule.normalized_raw_value = "класс a"
        self.field.value_type = "select_exact"
        self.db.commit()
        expected_ids = [v.id for v in self.field.allowed_values]
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE app_data_migrations (name TEXT PRIMARY KEY, details TEXT)"))
            migrate_attribute_value_keys(connection)
            migrate_attribute_value_keys(connection)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM app_data_migrations")).scalar(), 1)
        self.db.expire_all()
        self.assertEqual([v.id for v in self.field.allowed_values], expected_ids)
        self.assertEqual(allowed.normalized_value, "A")
        self.assertEqual(plus.normalized_value, "A+")
        self.assertEqual(plus.synonyms[0].normalized_synonym, "Класс A+")
        self.assertEqual(rule.normalized_raw_value, "Класс A+")
        self.assertEqual(rule.allowed_value_id, plus.id)
        self.assertEqual(self.field.value_type, "select")
        self.assertEqual(svc._saved_value_mapping(self.db, donor.id, self.field, "Класс A+"), "A+")

    def test_migration_refuses_to_merge_duplicate_records(self):
        from sqlalchemy import text
        from database.session import migrate_attribute_value_keys
        self.field.allowed_values[1].value = "A"
        self.db.commit()
        before = [(v.id, v.value, v.normalized_value) for v in self.field.allowed_values]
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE app_data_migrations (name TEXT PRIMARY KEY, details TEXT)"))
        with self.assertRaises(ValueError):
            with self.engine.begin() as connection:
                migrate_attribute_value_keys(connection)
        self.db.expire_all()
        self.assertEqual([(v.id, v.value, v.normalized_value) for v in self.field.allowed_values], before)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT count(*) FROM app_data_migrations")).scalar(), 0)


    def test_add_and_matching_keep_every_punctuation_variant(self):
        expected = ["A", "A+", "A++", "60/65", "60-65", "60 65"]
        self.assertEqual([v.value for v in self.field.allowed_values], expected)
        self.assertEqual(len({v.normalized_value for v in self.field.allowed_values}), len(expected))
        for value in expected:
            with self.subTest(value=value):
                self.assertEqual(svc._allowed_match(self.field, value)[0], value)
        existing = next(v for v in self.field.allowed_values if v.value == "A++")
        self.assertEqual(svc.add_allowed_value(self.db, self.field, "  A++  ").id, existing.id)
        lowercase = svc.add_allowed_value(self.db, self.field, "a++")
        self.assertNotEqual(lowercase.id, existing.id)
        self.assertEqual(svc._allowed_match(self.field, "a++")[0], "a++")

    def test_unknown_value_is_not_fuzzily_accepted_or_simplified(self):
        for value in ["A+++", "60.65", "A (старый)", "60/65 (см)"]:
            with self.subTest(value=value):
                canonical, confidence, _, _ = svc._allowed_match(self.field, value)
                self.assertEqual((canonical, confidence), ("", 0))
        self.field.conversion_rules = [{"from_value": "A+++", "to_value": "A"}]
        self.assertEqual(svc._allowed_match(self.field, "A+++")[0], "A")
        self.assertEqual(svc._allowed_match(self.field, "A++++")[0], "")

    def test_no_is_a_real_option_in_mixed_dictionary(self):
        svc.add_allowed_value(self.db, self.field, "Нет")
        svc.add_allowed_value(self.db, self.field, "Сверху")
        self.assertEqual(svc._allowed_match(self.field, "Нет")[0], "Нет")

    def test_search_and_value_hints_keep_plus_signs(self):
        result = svc.allowed_value_options(self.field, query="A++")
        self.assertEqual([v["value"] for v in result["values"]], ["A++"])
        result = svc._fields_with_exact_value([self.field], "A+++")
        self.assertEqual(result, [])
        self.assertEqual(svc._fields_with_exact_value([self.field], "A++"), [self.field])

    def test_synonyms_preserve_signs(self):
        allowed = next(v for v in self.field.allowed_values if v.value == "A++")
        svc.replace_allowed_value_synonyms(self.db, allowed, ["Класс+", "Класс++", " класс++ "])
        self.assertEqual([v.normalized_synonym for v in allowed.synonyms], ["Класс+", "Класс++", "класс++"])
        self.assertEqual(svc._allowed_match(self.field, "Класс++")[0], "A++")
        self.assertEqual(svc._allowed_match(self.field, "Класс+++")[0], "")

    def test_product_import_and_donor_conflict_keep_distinct_classes(self):
        product = self.product("A++")
        target = product.values[0]
        self.assertEqual((target.current_value, target.final_value), ("A++", "A++"))
        svc.apply_parsed_attributes(self.db, product, [{"name": "Класс", "value": "A"}],
                                    source="Донор", priority=0)
        self.assertEqual(target.status, "conflict")
        self.assertEqual(target.final_value, "A++")
        self.assertEqual(target.source_details["candidates"][0]["value"], "A")

    def test_unknown_product_value_remains_unknown(self):
        product = self.product("A+++")
        self.assertEqual(product.values[0].status, "unknown")
        self.assertEqual(product.values[0].final_value, "")

    def test_html_parser_does_not_deduplicate_distinct_classes(self):
        html = "<table><tr><td>Класс</td><td>A</td></tr><tr><td>Класс</td><td>A++</td></tr></table>"
        result = svc.parse_product_html(html)
        self.assertEqual([v["value"] for v in result["attributes"]], ["A", "A++"])

    def test_csv_update_and_template_history_preserve_exact_mode(self):
        revision = svc.save_template_revision(self.db, self.template, "test_exact")
        self.db.flush()
        payload = "Класс (Основные)\nA\nA+\nA++\nA+++\n".encode("utf-8")
        preview = svc.preview_template_csv(payload, self.template)
        self.assertEqual(preview["fields"][0]["value_type"], "select")
        self.assertEqual(preview["fields"][0]["added_values"], ["A+++"])
        svc.update_template_from_csv(self.db, self.template, payload, mode="replace")
        self.db.commit()
        self.assertEqual(svc._allowed_match(self.field, "A+++")[0], "A+++")
        svc.restore_template_revision(self.db, self.template, revision)
        self.db.commit()
        self.db.expire_all()
        self.assertEqual(self.field.value_type, "select")
        self.assertEqual([v.value for v in self.field.allowed_values], ["A", "A+", "A++", "60/65", "60-65", "60 65"])
        self.assertEqual(svc._allowed_match(self.field, "A++")[0], "A++")

    def test_single_value_restore_does_not_collide_with_a(self):
        allowed = next(v for v in self.field.allowed_values if v.value == "A++")
        revision = svc.save_allowed_value_revision(self.db, allowed, "test")
        self.db.flush()
        allowed.value, allowed.normalized_value = "A+++", "A+++"
        self.db.commit()
        svc.restore_template_revision(self.db, self.template, revision)
        self.db.commit()
        self.assertEqual((allowed.value, allowed.normalized_value), ("A++", "A++"))

    def test_saved_mapping_rules_distinguish_signs(self):
        brand = Brand(name="Test")
        donor = Donor(brand=brand, site_url="https://example.com")
        self.db.add(donor)
        self.db.flush()
        for raw in ["A", "A+", "A++"]:
            allowed = next(v for v in self.field.allowed_values if v.value == raw)
            svc.save_value_mapping_rule(self.db, donor_id=donor.id, field=self.field,
                                        raw_value=raw, allowed_value_id=allowed.id)
        self.db.flush()
        for raw in ["A", "A+", "A++"]:
            self.assertEqual(svc._saved_value_mapping(self.db, donor.id, self.field, raw), raw)
        self.assertEqual(svc._saved_value_mapping(self.db, donor.id, self.field, "A+++"), "")

    def test_ai_keeps_exact_value_and_rejects_fallback_for_unknown_variant(self):
        product = self.product()
        for value in ["A", "A+", "A++", "A+++"]:
            result = ai.validate_analysis(
                product, {"attributes": [{"source_id": 1, "field_id": self.field.id,
                                          "allowed_value": "A", "confidence": 85}]},
                source_facts=[{"source_id": 1, "name": "Класс", "value": value}],
            )
            if value == "A+++":
                self.assertEqual(result["suggestions"], [])
            else:
                self.assertEqual(result["suggestions"][0]["proposed_value"], value)
        self.assertEqual(ai._canonical_allowed(self.field, "A++"), "A++")
        self.assertEqual(ai._canonical_allowed(self.field, "A+++"), "")


    def test_ai_quote_must_confirm_the_exact_class(self):
        product = self.product()
        for value, quote, page in [
            ("A++", "Класс: A++", "Класс: A"),
            ("A", "Класс: A++", "Класс: A++"),
        ]:
            result = ai.validate_analysis(product, {"attributes": [{
                "name": "Класс", "value": value, "field_id": self.field.id, "evidence": quote,
            }]}, page_evidence=page)
            self.assertEqual(result["suggestions"], [])
        result = ai.validate_analysis(product, {"attributes": [{
            "name": "Класс", "value": "A++", "field_id": self.field.id, "evidence": "Класс: A++",
        }]}, page_evidence="Описание. Класс: A++")
        self.assertEqual(result["suggestions"][0]["proposed_value"], "A++")

    def test_old_csv_revision_does_not_reintroduce_lossy_matching(self):
        template = svc.import_template_csv(
            self.db, "Класс (Основные)\nB\n".encode("utf-8"), name="History CSV", category="History CSV",
        )
        revision = svc.save_template_revision(self.db, template, "before_upgrade")
        self.db.flush()
        svc.update_template_from_csv(self.db, template, "Класс (Основные)\nB++\n".encode("utf-8"))
        self.db.commit()
        svc.restore_template_revision(self.db, template, revision)
        self.db.commit()
        self.db.expire_all()
        self.assertEqual([v.value for v in template.fields[0].allowed_values], ["B"])
        self.assertEqual(template.fields[0].value_type, "select")
        self.assertEqual(svc._allowed_match(template.fields[0], "B++")[0], "")

    def test_api_edit_and_select_type_keep_exact_keys(self):
        from app import create_app
        allowed = next(v for v in self.field.allowed_values if v.value == "A++")
        with patch("services.application.SessionLocal", side_effect=lambda: Session(self.engine, expire_on_commit=False)):
            with patch("routes.attribute_assistant.ensure_storage"):
                app = create_app()
                app.config["TESTING"] = True
                client = app.test_client()
                with client.session_transaction() as session:
                    session["user_id"] = 1
                response = client.patch("/api/attribute-assistant/allowed-values/" + str(allowed.id),
                                        json={"value": "A+++"})
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                response = client.patch("/api/attribute-assistant/fields/" + str(self.field.id),
                                        json={"value_type": "select"})
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.db.expire_all()
        self.assertEqual(allowed.normalized_value, "A+++")
        self.assertEqual(self.field.value_type, "select")

    def test_every_new_field_has_literal_keys(self):
        field = svc.create_template_field(self.db, self.template, group_name="Основные", name="Режим")
        value = svc.add_allowed_value(self.db, field, "B++", synonym="Класс B++")
        self.assertEqual(value.normalized_value, "B++")
        svc.set_field_value_type(self.db, field, "select")
        self.assertEqual(value.normalized_value, "B++")
        self.assertEqual(value.synonyms[0].normalized_synonym, "Класс B++")
        plain = svc.add_allowed_value(self.db, field, "B")
        self.assertNotEqual(plain.id, value.id)
        self.assertEqual(svc._allowed_match(field, "B++")[0], "B++")


if __name__ == "__main__":
    unittest.main()
