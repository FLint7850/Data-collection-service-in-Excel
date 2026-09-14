import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, AttributeBatch, AttributeProduct
from services import attribute_assistant as svc
from services import attribute_ai as ai


class AttributeReviewRulesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "test.db"))
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.storage = patch.object(svc, "ATTRIBUTE_ASSISTANT_DIR", Path(self.temp.name))
        self.storage.start()

    def tearDown(self):
        self.storage.stop()
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def template(self, name="Класс", values=("A", "A+", "A++"), value_type="select"):
        data = (name + " (Основные)\n" + "\n".join(values) + "\n").encode("utf-8")
        template = svc.import_template_csv(self.db, data, name=name, category=name)
        template.fields[0].value_type = value_type
        for value in values:
            svc.add_allowed_value(self.db, template.fields[0], value)
        return template

    def product(self, template, current="", source_name="", mode="suggest"):
        batch = AttributeBatch(template=template, name="Check", input_mode="urls", processing_mode=mode)
        product = AttributeProduct(batch=batch, template=template, model="TEST", name="Test", source_url="https://shop.example/product")
        field = template.fields[0]
        stack = [{"name": field.name, "group_name": field.group_name, "value": current, "source_name": source_name or field.name}] if current else []
        svc._make_product_values(product, template, stack, current_source="current_site")
        self.db.add(batch)
        self.db.flush()
        return product

    def analyze(self, product, name, value, allowed=None):
        record = {"source_id": 1, "field_id": product.template.fields[0].id, "confidence": 85}
        if allowed:
            record["allowed_value"] = allowed
        return ai.validate_analysis(product, {"attributes": [record]}, source_facts=[{"name": name, "value": value}])

    def test_linear_sizes_use_centimeters_for_every_field_type_and_source(self):
        cases = [
            ("Ширина, см", "Ширина, мм", "600", "60"),
            ("Ширина, см", "Ширина, м", "0,6", "60"),
            ("Ширина, см", "Ширина, см", "60", "60"),
            ("Ширина", "Ширина", "600 мм", "60"),
            ("Ширина", "Ширина (миллиметры)", "600 миллиметров", "60"),
            ("Ширина", "Ширина (в миллиметрах)", "600", "60"),
            ("Ширина", "Ширина (метры)", "0.6", "60"),
            ("Ширина", "Width, mm", "600", "60"),
            ("Длина", "Длина, м", "1.234", "123.4"),
        ]
        for index, (field_name, source_name, raw, expected) in enumerate(cases):
            for kind in ["select", "number"]:
                with self.subTest(raw=raw, source_name=source_name, kind=kind):
                    template = self.template(field_name + " " + str(index) + kind, (expected,), kind)
                    field = template.fields[0]
                    self.assertEqual(svc._allowed_match(field, raw, source_name)[0], expected)
                    product = self.product(template, raw, source_name)
                    self.assertEqual(product.values[0].final_value, expected)
                    self.assertEqual(product.values[0].current_value, raw)
                    parsed = self.product(template)
                    with patch.object(svc, "map_attribute", return_value=(field, 100, "Mapped", [])):
                        svc.apply_parsed_attributes(self.db, parsed, [{"name": source_name, "value": raw}], source="Donor", priority=0)
                    self.assertEqual(parsed.values[0].proposed_value, expected)
                    # Explicit GPT field mapping must use the very same source units.
                    analysis = self.analyze(parsed, source_name, raw)
                    self.assertEqual(analysis["suggestions"][0]["proposed_value"], expected)

    def test_dimension_tuples_and_ranges_keep_order_and_separators(self):
        template = self.template("Габариты, см", ("60x45x85", "60/65", "60-65"))
        field = template.fields[0]
        cases = [("600 x 450 x 850 мм", "Габариты"), ("0,6 × 0,45 × 0,85 м", "Габариты"),
                 ("600 мм x 45 см x 0.85 м", "Габариты"), ("60x45x85", "Габариты, см"),
                 ("600x450x850", "Габариты, мм")]
        for value, name in cases:
            with self.subTest(value=value):
                self.assertEqual(svc._allowed_match(field, value, name)[0], "60x45x85")
        self.assertEqual(svc._allowed_match(field, "600/650 мм", "Габариты")[0], "60/65")
        self.assertEqual(svc._allowed_match(field, "600-650 мм", "Габариты")[0], "60-65")
        field.value_type = "dimensions"
        self.assertEqual(svc._allowed_match(field, "0.6x0.45x0.85 м", "Габариты")[0], "60x45x85")

    def test_conversion_does_not_fall_back_to_unconverted_number(self):
        template = self.template("Ширина, см", ("180",))
        field = template.fields[0]
        for raw, source in [("180", "Ширина, мм"), ("1.8", "Ширина, см")]:
            canonical, _, _, suggestions = svc._allowed_match(field, raw, source)
            self.assertEqual(canonical, "")
            self.assertEqual(suggestions, [])
        self.assertEqual(svc._allowed_match(field, "180 см", "Ширина, мм")[0], "180")

    def test_non_length_values_are_not_scaled(self):
        for value, name in [("60", "Площадь, м²"), ("60", "Расход, м³/ч"), ("60", "Скорость, м/с"), ("60/65", "Класс")]:
            self.assertIsNone(svc._centimeter_value(value, name, name))
        field = self.template("Мощность, Вт", ("1200",), "number").fields[0]
        self.assertEqual(svc._allowed_match(field, "1.2 кВт")[0], "1200")

    def test_bad_original_is_conflict_or_manual_suggestion(self):
        template = self.template()
        for raw, status in [("совершенно другое", "conflict"), ("A+++", "suggested")]:
            product = self.product(template, raw, mode="auto_all")
            value = product.values[0]
            self.assertEqual(value.status, status)
            self.assertEqual(value.current_value, raw)
            self.assertEqual(value.final_value, "")
            self.assertEqual(value.source_details["unknown_values"][0]["value"], raw)
            svc._recalculate_candidate_state(product, value)
            self.assertEqual(value.status, status)
            self.assertEqual(value.final_value, "")
            svc.refresh_product_status(product)
            self.assertEqual(product.status, "needs_review")

    def test_parser_and_gpt_keep_mapped_bad_values_and_same_status(self):
        template = self.template()
        for raw, status in [("совершенно другое", "conflict"), ("A+++", "suggested")]:
            for method in ["parser", "gpt"]:
                with self.subTest(raw=raw, method=method):
                    product = self.product(template, mode="auto_all")
                    value = product.values[0]
                    if method == "parser":
                        svc.apply_parsed_attributes(self.db, product, [{"name": "Класс", "value": raw}], source="Donor", priority=0)
                    else:
                        analysis = self.analyze(product, "Класс", raw)
                        self.assertEqual(analysis["suggestions"], [])
                        self.assertEqual(analysis["unmatched_attributes"][0]["template_field_id"], template.fields[0].id)
                        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
                    self.assertEqual(value.status, status)
                    self.assertEqual(value.final_value, "")
                    self.assertEqual(value.source_details["unknown_values"][0]["value"], raw)
                    self.assertEqual(bool(value.proposed_value), status == "suggested")
                    svc.refresh_batch_summary(product.batch)
                    self.assertEqual(product.batch.summary["conflicts"], int(status == "conflict"))
                    self.assertEqual(product.batch.summary["suggestions"], int(status == "suggested"))

    def test_gpt_semantic_alternative_is_not_auto_accepted(self):
        template = self.template("Цвет", ("Белый",))
        product = self.product(template, mode="auto_all")
        analysis = self.analyze(product, "Цвет", "снежный", "Белый")
        self.assertEqual(analysis["suggestions"], [])
        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
        self.assertEqual(product.values[0].status, "suggested")
        self.assertEqual(product.values[0].proposed_value, "Белый")
        self.assertEqual(product.values[0].final_value, "")

    def test_gpt_clears_old_unmatched_fact_on_next_successful_analysis(self):
        template = self.template()
        product = self.product(template)
        for raw in ["совершенно другое", "A++"]:
            analysis = self.analyze(product, "Класс", raw)
            ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
        value = product.values[0]
        self.assertEqual(value.status, "suggested")
        self.assertEqual(value.proposed_value, "A++")
        self.assertFalse(value.source_details.get("unknown_values"))

    def test_valid_original_and_disagreeing_source_remain_conflict(self):
        template = self.template()
        product = self.product(template, "A++")
        analysis = self.analyze(product, "Класс", "A+")
        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
        self.assertEqual(product.values[0].status, "conflict")
        self.assertEqual(product.values[0].final_value, "A++")

    def test_invalid_original_with_valid_candidate_is_suggested(self):
        template = self.template()
        product = self.product(template, "A+++")
        svc.apply_parsed_attributes(self.db, product, [{"name": "Класс", "value": "A++"}], source="Donor", priority=0)
        self.assertEqual(product.values[0].status, "suggested")
        self.assertEqual(product.values[0].proposed_value, "A++")
        self.assertEqual(product.values[0].final_value, "")

    def test_centimeter_dictionary_format_is_preserved(self):
        field = self.template("Габариты, см", ("60 x 45 x 85",)).fields[0]
        self.assertEqual(svc._allowed_match(field, "60 x 45 x 85", "Габариты, см")[0], "60 x 45 x 85")
        self.assertEqual(svc._allowed_match(field, "600 x 450 x 850", "Габариты, мм")[0], "60 x 45 x 85")
        field = self.template("Ширина, см", ("60,0",)).fields[0]
        self.assertEqual(svc._allowed_match(field, "60,0", "Ширина, см")[0], "60,0")

    def test_invalid_donor_value_is_visible_even_with_valid_original(self):
        template = self.template()
        for raw, status in [("совершенно другое", "conflict"), ("A+++", "suggested")]:
            for method in ["parser", "gpt"]:
                with self.subTest(raw=raw, method=method):
                    product = self.product(template, "A++", mode="auto_all")
                    if method == "parser":
                        svc.apply_parsed_attributes(self.db, product, [{"name": "Класс", "value": raw}], source="Donor", priority=0)
                    else:
                        ai.apply_analysis(self.db, product, self.analyze(product, "Класс", raw), source_url=product.source_url)
                    self.assertEqual(product.values[0].status, status)
                    self.assertEqual(product.values[0].final_value, "A++")
                    self.assertEqual(product.values[0].source_details["unknown_values"][0]["value"], raw)

    def test_confirmed_original_clears_stale_alternative_after_reanalysis(self):
        template = self.template()
        product = self.product(template, "A")
        analysis = self.analyze(product, "Класс", "A+++")
        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
        self.assertEqual(product.values[0].proposed_value, "A++")
        analysis = self.analyze(product, "Класс", "A")
        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
        self.assertEqual(product.values[0].status, "kept")
        self.assertEqual(product.values[0].final_value, "A")
        self.assertEqual(product.values[0].proposed_value, "")
        self.assertFalse(product.values[0].source_details.get("unknown_values"))

    def test_unrestricted_numeric_fields_keep_valid_format_in_centimeters(self):
        for index, (name, kind, raw, expected) in enumerate([
            ("Ширина", "number", "600 мм", "60"),
            ("Ширина", "number", "60,0 см", "60"),
            ("Габариты", "dimensions", "0.6 x 0.45 x 0.85 м", "60x45x85"),
        ]):
            with self.subTest(kind=kind, raw=raw):
                field = self.template(name + " " + str(index), (expected,), kind).fields[0]
                for item in field.allowed_values:
                    item.is_active = False
                self.assertEqual(svc._allowed_match(field, raw, name)[0], expected)

    def test_invalid_source_reopens_automatic_acceptance_in_any_order(self):
        template = self.template()
        for reverse in [False, True]:
            for method in ["parser", "gpt"]:
                with self.subTest(reverse=reverse, method=method):
                    product = self.product(template, mode="auto_all")
                    facts = [("Good donor", "A++"), ("Bad donor", "совершенно другое")]
                    if reverse:
                        facts.reverse()
                    for source, raw in facts:
                        if source == "Bad donor" and method == "gpt":
                            ai.apply_analysis(self.db, product, self.analyze(product, "Класс", raw), source_url=product.source_url)
                        else:
                            svc.apply_parsed_attributes(self.db, product, [{"name": "Класс", "value": raw}], source=source, priority=0)
                    self.assertEqual(product.values[0].status, "suggested")
                    self.assertEqual(product.values[0].proposed_value, "A++")
                    self.assertEqual(product.values[0].final_value, "")

    def test_invalid_reanalysis_replaces_auto_accepted_gpt_result(self):
        template = self.template()
        product = self.product(template, mode="auto_all")
        ai.apply_analysis(self.db, product, self.analyze(product, "Класс", "A++"), source_url=product.source_url)
        self.assertEqual(product.values[0].status, "approved")
        ai.apply_analysis(self.db, product, self.analyze(product, "Класс", "совершенно другое"), source_url=product.source_url)
        self.assertEqual(product.values[0].status, "conflict")
        self.assertEqual(product.values[0].final_value, "")
        self.assertFalse(product.values[0].source_details.get("candidates"))

    def test_manual_confirmation_survives_invalid_reanalysis(self):
        template = self.template()
        product = self.product(template, mode="auto_all")
        ai.apply_analysis(self.db, product, self.analyze(product, "Класс", "A++"), source_url=product.source_url)
        value = product.values[0]
        svc.update_product_value(value, action="accept")
        ai.apply_analysis(self.db, product, self.analyze(product, "Класс", "совершенно другое"), source_url=product.source_url)
        self.assertEqual(value.status, "approved")
        self.assertEqual(value.final_value, "A++")
        self.assertEqual(value.source_details["unknown_values"][0]["value"], "совершенно другое")

    def test_value_case_is_ignored_by_import_parser_and_gpt(self):
        template = self.template("Тип установки", ("Встраиваемый",))
        field = template.fields[0]
        for raw in ["встраиваемый", "ВСТРАИВАЕМЫЙ", "ВсТрАиВаЕмЫй"]:
            with self.subTest(raw=raw):
                self.assertEqual(svc._allowed_match(field, raw)[:2], ("Встраиваемый", 100))
                imported = self.product(template, raw)
                self.assertEqual(imported.values[0].current_value, raw)
                self.assertEqual(imported.values[0].final_value, "Встраиваемый")
                self.assertEqual(imported.values[0].status, "kept")
                for method in ["parser", "gpt"]:
                    product = self.product(template)
                    if method == "parser":
                        svc.apply_parsed_attributes(self.db, product, [{"name": field.name, "value": raw}], source="Donor", priority=0)
                    else:
                        analysis = self.analyze(product, field.name, raw)
                        self.assertFalse(analysis["unmatched_attributes"])
                        ai.apply_analysis(self.db, product, analysis, source_url=product.source_url)
                    value = product.values[0]
                    self.assertEqual(value.proposed_value, "Встраиваемый")
                    self.assertEqual(value.status, "suggested")
                    self.assertFalse(value.source_details.get("unknown_values"))
                    self.assertEqual(value.source_details["candidates"][0]["raw_value"], raw)

    def test_case_variants_in_existing_dictionary_do_not_create_source_conflict(self):
        template = self.template("Тип установки", ("Встраиваемый", "встраиваемый"))
        field = template.fields[0]
        original_records = [(item.id, item.value, item.normalized_value) for item in field.allowed_values]
        product = self.product(template, "Встраиваемый")
        svc.apply_parsed_attributes(self.db, product, [{"name": field.name, "value": "встраиваемый"}], source="Donor", priority=0)
        ai.apply_analysis(self.db, product, self.analyze(product, field.name, "встраиваемый"), source_url=product.source_url)
        self.assertEqual(product.values[0].status, "kept")
        self.assertEqual(product.values[0].final_value, "Встраиваемый")
        self.assertEqual(original_records, [(item.id, item.value, item.normalized_value) for item in field.allowed_values])
        self.assertEqual(ai._canonical_allowed(field, "ВСТРАИВАЕМЫЙ"), "Встраиваемый")

    def test_ignore_case_preserves_signs_spaces_and_distinct_letters(self):
        field = self.template("Класс", ("A", "A+", "A++", "60/65", "60-65", "A B", "Ё", "ß")).fields[0]
        for raw, expected in [("a", "A"), ("a+", "A+"), ("a++", "A++"), ("a b", "A B"), ("ё", "Ё")]:
            self.assertEqual(svc._allowed_match(field, raw)[0], expected)
            self.assertEqual(ai._canonical_allowed(field, raw), expected)
        for raw in ["a+++", "60.65", "60_65", "a  b", "ab", "а", "е", "SS"]:
            with self.subTest(raw=raw):
                self.assertEqual(svc._allowed_match(field, raw)[0], "")
                self.assertEqual(ai._canonical_allowed(field, raw), "")
        self.assertEqual(svc._allowed_match(field, "60/65")[0], "60/65")
        self.assertEqual(svc._allowed_match(field, "60-65")[0], "60-65")

    def test_case_is_ignored_in_value_hints_and_nearest_suggestions(self):
        field = self.template("Тип установки", ("Встраиваемый",)).fields[0]
        index = svc._allowed_value_field_index([field], {"ВСТРАИВАЕМЫЙ"})
        self.assertEqual(svc._fields_with_exact_value([field], "встраиваемый", index), [field])
        lower = svc._allowed_match(field, "встраиваемая")
        upper = svc._allowed_match(field, "ВСТРАИВАЕМАЯ")
        self.assertEqual(lower, upper)
        self.assertEqual(lower[0], "")
        self.assertIn("Встраиваемый", lower[3])

    def test_synonyms_and_saved_rules_ignore_case_but_keep_signs(self):
        from models import Brand, Donor
        field = self.template("Класс", ("A", "A++")).fields[0]
        allowed = next(item for item in field.allowed_values if item.value == "A++")
        svc.replace_allowed_value_synonyms(self.db, allowed, ["Класс++"])
        self.assertEqual(svc._allowed_match(field, "КЛАСС++")[0], "A++")
        self.assertEqual(svc._allowed_match(field, "КЛАСС+")[0], "")
        donor = Donor(brand=Brand(name="Case test"), site_url="https://example.com")
        self.db.add(donor)
        self.db.flush()
        svc.save_value_mapping_rule(self.db, donor_id=donor.id, field=field, raw_value="Класс++", allowed_value_id=allowed.id)
        self.db.flush()
        self.assertEqual(svc._saved_value_mapping(self.db, donor.id, field, "КЛАСС++"), "A++")
        self.assertEqual(svc._saved_value_mapping(self.db, donor.id, field, "КЛАСС+"), "")
