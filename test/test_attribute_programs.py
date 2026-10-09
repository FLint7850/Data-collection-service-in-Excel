import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import (Base, AttributeAllowedValue, AttributeBatch, AttributeCategory,
                    AttributeProduct, AttributeTemplate, AttributeTemplateField)
from services import attribute_ai as ai
from services import attribute_assistant as svc
from services.attribute_programs import is_program_list, match_programs, program_dictionary


def field(values, name="Список программ", group="Программы", separator="/", synonyms=None):
    records = [SimpleNamespace(value=value, is_active=True, synonyms=[]) for value in values]
    for canonical, aliases in (synonyms or {}).items():
        record = next((item for item in records if item.value == canonical), None)
        if record is None:
            record = SimpleNamespace(value=canonical, is_active=True, synonyms=[])
            records.append(record)
        record.synonyms = [SimpleNamespace(synonym=alias) for alias in aliases]
    return SimpleNamespace(name=name, group_name=group, value_type="select", is_composite=False,
                           separator=separator, allowed_values=records)


class ProgramNormalizationTest(unittest.TestCase):
    def test_large_prompt_vocabulary_is_relevant_but_full_validation_is_preserved(self):
        programs = field([f"Режим {index}" for index in range(100)],
                         synonyms={"Режим 88": ["Мой цикл"]})
        hints = program_dictionary(programs, "Программы: Режим 7; Мой цикл")
        self.assertEqual(hints['program_components'], ['Режим 7', 'Режим 88'])
        self.assertEqual(hints['program_components_total'], 100)
        self.assertEqual(hints['program_synonyms'], {'мой цикл': 'Режим 88'})
        self.assertEqual(match_programs(programs, 'Режим 99')[0], 'Режим 99')
        programs.allowed_values[88].is_active = False
        hints = program_dictionary(programs, 'Мой цикл')
        self.assertEqual(hints['program_components'], [])
        self.assertNotIn('program_synonyms', hints)
        self.assertEqual(match_programs(programs, 'Мой цикл')[0], '')

    def test_historical_combinations_define_the_component_vocabulary(self):
        programs = field(["хлопок/Шерсть/Полоскание и отжим", "Детские вещи/ЭКО/Экспресс"],
                         synonyms={"Детские вещи": ["Детское белье"]})
        result = match_programs(programs, "шерсть; Детское белье, ХЛОПОК / Полоскание и отжим / хлопок")
        self.assertEqual(result[0], "Детские вещи/Полоскание и отжим/Хлопок/Шерсть")
        self.assertEqual(result[1], 100)
        self.assertEqual(result[3], [])

    def test_space_separated_source_and_program_details(self):
        programs = field(["Хлопок/Спортивная одежда/Ежедневная/ЭКО/Экспресс"])
        result = match_programs(programs, "Хлопок Спортивная одежда 20°С Ежедневная 45’ ЭКО 40–60 Экспресс 15'")
        self.assertEqual(result[0], "Ежедневная/Спортивная одежда/Хлопок/ЭКО/Экспресс")
        self.assertEqual(result[1], 100)

    def test_detailed_programs_keep_their_distinct_numbers(self):
        programs = field(["20 °C/Интенсивная/Очистка барабана/ECO 40-60 °C/Экспресс 15'"],
                         synonyms={"Очистка барабана": ["Автоочистка"]})
        result = match_programs(programs, "Автоочистка; eco 40–60; Экспресс 15 мин.; 20°С")
        self.assertEqual(result[0], "20 °C/ECO 40-60 °C/Очистка барабана/Экспресс 15'")
        self.assertEqual(result[1], 100)
        for unknown in ["Экспресс 30 минут", "60°C", "ECO 20-40", "Полностью неизвестная"]:
            self.assertEqual(match_programs(programs, unknown)[0], "")
        programs = field(["Предварительная стирка/Очистка барабана"],
                         synonyms={"Предварительная стирка": ["Функция предварительной стирки"]})
        self.assertEqual(match_programs(programs, "Функция предварительной стирки")[0], "Предварительная стирка")

    def test_unknown_and_inactive_programs_never_enter_the_result(self):
        programs = field(["Хлопок/Шерсть", "Интенсивная"])
        programs.allowed_values[1].is_active = False
        result = match_programs(programs, "Хлопок/Интенсивная/Новая программа")
        self.assertEqual(result[0], "Хлопок")
        self.assertIn("интенсивная", result[2])
        self.assertIn("новая программа", result[2])
        self.assertEqual(result[3], [])
        self.assertEqual(match_programs(programs, "Не хлопок")[0], "")

    def test_saved_component_and_whole_list_synonyms(self):
        programs = field(["Хлопок", "Шерсть", "Полоскание и отжим/Хлопок"])
        programs.allowed_values[0].synonyms = [SimpleNamespace(synonym="Лен и хлопок")]
        programs.allowed_values[2].synonyms = [SimpleNamespace(synonym="Набор А")]
        self.assertEqual(match_programs(programs, "Лен и хлопок / Шерсть")[0], "Хлопок/Шерсть")
        self.assertEqual(match_programs(programs, "Набор А")[0], "Полоскание и отжим/Хлопок")
        programs.allowed_values[1].synonyms = [SimpleNamespace(synonym="Лен и хлопок")]
        self.assertEqual(match_programs(programs, "Лен и хлопок")[0], "")
        self.assertIn("Неоднозначный", match_programs(programs, "Лен и хлопок")[2])

    def test_all_program_sections_and_custom_separators(self):
        for name in ["Программы стирки", "Дополнительные программы мойки", "Список программ сушки", "Основные режимы"]:
            programs = field(["Шерсть|Хлопок"], name=name, separator="|")
            self.assertTrue(is_program_list(programs))
            self.assertEqual(match_programs(programs, "хлопок|шерсть")[0], "Хлопок/Шерсть")
        for name, values in [("Количество программ", ["12", "15"]),
                             ("Звуковой сигнал в конце программы", ["Есть", "Нет"]),
                             ("Автопрограммы приготовления", ["Есть", "Нет"])]:
            self.assertFalse(is_program_list(field(values, name=name)))
        programs = field(["Хлопок (стирка/сушка)/Шерсть"])
        self.assertEqual(match_programs(programs, "Хлопок (стирка/сушка)")[0], "Хлопок (стирка/сушка)")

    def test_program_names_and_synonyms_come_only_from_current_dictionary(self):
        programs = field(["Детские вещи/Очистка барабана/Хлопок"])
        for raw in ["Детское белье", "Автоочистка", "Cotton", "Новая программа"]:
            self.assertEqual(match_programs(programs, raw)[0], "")
        programs.allowed_values.append(SimpleNamespace(value="новая программа", is_active=True,
                                                       synonyms=[SimpleNamespace(synonym="Новый режим")]))
        self.assertEqual(match_programs(programs, "Новый режим/Хлопок")[0], "Новая программа/Хлопок")
        programs.allowed_values[-1].value = "Обновленная программа"
        self.assertEqual(match_programs(programs, "Новый режим")[0], "Обновленная программа")
        self.assertEqual(match_programs(programs, "Новая программа")[0], "")
        programs.allowed_values[-1].synonyms = []
        self.assertEqual(match_programs(programs, "Новый режим")[0], "")
        programs.allowed_values[-1].is_active = False
        self.assertEqual(match_programs(programs, "Обновленная программа")[0], "")

    def test_dictionary_names_are_not_merged_without_saved_synonyms(self):
        programs = field(["Автоочистка/Очистка барабана"])
        self.assertEqual(match_programs(programs, "Автоочистка/Очистка барабана")[0],
                         "Автоочистка/Очистка барабана")


class ProgramAndProposalIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def product(self, values, name="Список программ", current="", mode="suggest"):
        template = AttributeTemplate(name=name, category=AttributeCategory(name=name, full_path=name))
        group = "Программы" if "программ" in name.casefold() else "Основные"
        programs = AttributeTemplateField(template=template, name=name, group_name=group,
                                         value_type="select", is_composite=False)
        for index, value in enumerate(values):
            programs.allowed_values.append(AttributeAllowedValue(value=value, normalized_value=value,
                                                                 is_active=True, is_combination=False, sort_order=index))
        batch = AttributeBatch(template=template, name="Test", input_mode="urls", processing_mode=mode)
        product = AttributeProduct(batch=batch, template=template, name="Test", model="TEST")
        self.db.add(batch)
        self.db.flush()
        svc._make_product_values(product, template, [{"name": name, "group_name": group, "value": current}] if current else [])
        self.db.flush()
        return product

    def test_parser_and_chatgpt_use_same_whitelist_for_legacy_templates(self):
        product = self.product(["Шерсть/Хлопок/Полоскание и отжим"])
        raw = "ХЛОПОК Полоскание и отжим Шерсть Хлопок Неизвестная"
        svc.apply_parsed_attributes(self.db, product, [{"name": "Список программ", "value": raw}], source="Donor", priority=0)
        self.assertEqual(product.values[0].proposed_value, "Полоскание и отжим/Хлопок/Шерсть")
        analysis = ai.validate_analysis(product, {"attributes": [{"source_id": 1, "field_id": product.template.fields[0].id,
                                                                 "confidence": 85}]},
                                        source_facts=[{"name": "Список программ", "value": raw}])
        self.assertEqual(analysis["unmatched_attributes"], [])
        ai.apply_analysis(self.db, product, analysis, source_url="https://example.com/product")
        self.assertTrue(all(item["value"] == "Полоскание и отжим/Хлопок/Шерсть"
                            for item in product.values[0].source_details["candidates"]))
        self.assertTrue(all(item["raw_value"] == raw for item in product.values[0].source_details["candidates"]))

    def test_original_and_confirming_source_are_kept_despite_order_and_synonyms(self):
        product = self.product(["Детские вещи/Хлопок/Шерсть"], current="Шерсть/Детские вещи/Хлопок")
        programs = product.template.fields[0]
        for canonical, alias in [("Хлопок", "Cotton"), ("Детские вещи", "Детское белье"), ("Шерсть", "Wool")]:
            svc.add_allowed_value(self.db, programs, canonical, synonym=alias)
        self.db.flush()
        svc.apply_parsed_attributes(self.db, product, [{"name": "Список программ", "value": "Cotton Детское белье Wool"}],
                                    source="Donor", priority=0)
        target = product.values[0]
        self.assertEqual(target.status, "kept")
        self.assertEqual(target.final_value, "Детские вещи/Хлопок/Шерсть")
        self.assertEqual(target.proposed_value, "")
        self.assertTrue(target.source_details["candidates"][0]["matches_current"])

    def test_unmatched_source_with_same_nearest_alternative_requires_review_without_a_proposal(self):
        product = self.product(["Отдельностоящий", "Встраиваемый"], name="Тип установки", current="Отдельностоящий")
        target = product.values[0]
        svc.record_unknown_value(product, target, raw_value="Отдельностоящая техника", source="ChatGPT",
                                 source_name="Тип", suggestions=["Отдельностоящий"], reason="Нет в справочнике")
        self.assertEqual(target.status, "conflict")
        self.assertEqual(target.proposed_value, "")
        self.assertEqual(svc.refresh_batch_summary(product.batch)["suggestions"], 0)
        self.assertEqual(svc.refresh_product_status(product), "needs_review")

    def test_historical_same_suggestion_is_removed_but_real_changes_remain(self):
        product = self.product(["Отдельностоящий", "Встраиваемый"], name="Тип установки", current="Отдельностоящий")
        target = product.values[0]
        target.status, target.proposed_value = "suggested", "отдельностоящий"
        serialized = svc.serialize_value(target)
        self.assertEqual(serialized["status"], "kept")
        self.assertEqual(serialized["proposed_value"], "")
        target.status, target.proposed_value = "suggested", "Встраиваемый"
        self.assertEqual(svc.serialize_value(target)["status"], "conflict")

    def test_manually_accepted_programs_are_normalized(self):
        product = self.product(["Хлопок/Шерсть"])
        svc.update_product_value(product.values[0], action="accept", manual_value="шерсть/хлопок/шерсть")
        self.assertEqual(product.values[0].final_value, "Хлопок/Шерсть")

    def test_rejection_preserves_only_allowed_original_programs(self):
        product = self.product(["Хлопок/Шерсть"], current="шерсть/хлопок/Неизвестная")
        svc.update_product_value(product.values[0], action="reject")
        self.assertEqual(product.values[0].final_value, "Хлопок/Шерсть")
        self.assertEqual(product.values[0].current_value, "шерсть/хлопок/Неизвестная")


if __name__ == "__main__":
    unittest.main()
