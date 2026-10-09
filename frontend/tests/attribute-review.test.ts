import { describe, expect, it } from "vitest";
import type { AttributeValue } from "../app/types/attribute-assistant";
import {
  attributeValuesMatch, canConfirmConflictFinal, displayedProposal, hasPendingProposal, matchesAttributeStatus, originalValueHints,
  valueStatusColor, valueStatusLabel,
} from "../app/utils/attribute-assistant";

function value(overrides: Partial<AttributeValue> = {}): AttributeValue {
  return {
    id: 1, field_id: 1, group_name: "Основные", name: "Класс", current_value: "A+++",
    proposed_value: "", final_value: "", source: "current_site", confidence: 0,
    status: "conflict", reason: "Нет в справочнике", dash_reason: "", is_in_template: true,
    is_extra: false, value_type: "select", is_composite: false, allowed_values_count: 3,
    allowed_values: [], source_details: {}, sort_order: 0, ...overrides,
  };
}

const unknown = { value: "A+++", source: "Donor", source_name: "Класс", suggestions: ["A++"], reason: "Нет в справочнике" };

describe("attribute dictionary review", () => {
  it("shows a bad original as conflict and includes it only in the conflict filter", () => {
    const row = value();
    expect(valueStatusLabel(row)).toBe("Конфликт");
    expect(valueStatusColor(row)).toBe("error");
    expect(matchesAttributeStatus(row, "conflict")).toBe(true);
    expect(matchesAttributeStatus(row, "suggested")).toBe(false);
    expect(matchesAttributeStatus(row, "no_suggestion")).toBe(false);
  });

  it("keeps suggestions visibly separate from an accepted final value", () => {
    const row = value({ current_value: "", status: "suggested", proposed_value: "A++" });
    expect(valueStatusLabel(row)).toBe("Есть предложение");
    expect(valueStatusColor(row)).toBe("warning");
    expect(matchesAttributeStatus(row, "suggested")).toBe(true);
    expect(matchesAttributeStatus(row, "conflict")).toBe(false);
    expect(matchesAttributeStatus(row, "no_suggestion")).toBe(false);
    expect(hasPendingProposal(row)).toBe(true);
    expect(row.final_value).toBe("");
    expect(displayedProposal(row)).toBe("A++");
    // A donor alternative can confirm the current value while still requiring review.
    row.final_value = "A++";
    expect(matchesAttributeStatus(row, "suggested")).toBe(true);
  });

  it("supports older unknown records without confusing missing fields or rejected rows", () => {
    const row = value({ current_value: "", status: "unknown", source_details: { unknown_values: [unknown] } });
    expect(displayedProposal(row)).toBe("A++");
    expect(valueStatusLabel(row)).toBe("Есть предложение");
    expect(matchesAttributeStatus(row, "suggested")).toBe(true);
    row.source_details.unknown_values![0] = { ...unknown, suggestions: [] };
    expect(matchesAttributeStatus(row, "conflict")).toBe(true);
    expect(valueStatusColor(row)).toBe("error");
    expect(matchesAttributeStatus(value({ status: "missing", current_value: "" }), "no_suggestion")).toBe(true);
    expect(hasPendingProposal(value({ status: "rejected", proposed_value: "A++" }))).toBe(false);
    expect(matchesAttributeStatus(value({ is_in_template: false }), "conflict")).toBe(false);
  });

  it("retains the raw source and conversion explanation under the original value", () => {
    const row = value({ source_details: {
      current_value_hint: "Ширина, мм: 600 → 60 см",
      unknown_values: [unknown, unknown],
    } });
    expect(originalValueHints(row)).toEqual(["Ширина, мм: 600 → 60 см", "Класс: A+++ — Нет в справочнике"]);
  });

  it.each(["suggested", "unknown"])("classifies old %s rows with an original value as conflicts", (status) => {
    const row = value({ status, current_value: "A+++", proposed_value: "A++",
      source_details: { unknown_values: [unknown] } });
    expect(valueStatusLabel(row)).toBe("Конфликт");
    expect(valueStatusColor(row)).toBe("error");
    expect(matchesAttributeStatus(row, "conflict")).toBe(true);
    expect(matchesAttributeStatus(row, "suggested")).toBe(false);
    expect(displayedProposal(row)).toBe("A++");
    expect(hasPendingProposal(row)).toBe(true);
    row.current_value = "";
    expect(matchesAttributeStatus(row, "suggested")).toBe(true);
    expect(matchesAttributeStatus(row, "conflict")).toBe(false);
  });
});


describe("attribute value letter case", () => {
  it.each(["Отдельностоящий", "1300", "24"])("hides unchanged suggestions for %s, including older saved statuses", (original) => {
    const row = value({ status: "suggested", current_value: original, proposed_value: original,
      final_value: original, source_details: { candidates: [{ value: original, raw_value: original,
        source: "ChatGPT", confidence: 85, reason: "Подтверждено", priority: 90, source_name: "Тип" }] } });
    expect(displayedProposal(row)).toBe("");
    expect(valueStatusLabel(row)).toBe("Без изменений");
    expect(valueStatusColor(row)).toBe("success");
    expect(hasPendingProposal(row)).toBe(false);
    expect(matchesAttributeStatus(row, "suggested")).toBe(false);
    expect(matchesAttributeStatus(row, "no_suggestion")).toBe(true);
  });

  it("retains a real disagreement even when one candidate confirms the original", () => {
    const row = value({ status: "conflict", current_value: "24", proposed_value: "24", final_value: "24" });
    expect(displayedProposal(row)).toBe("");
    expect(hasPendingProposal(row)).toBe(false);
    expect(valueStatusLabel(row)).toBe("Конфликт");
    expect(matchesAttributeStatus(row, "conflict")).toBe(true);
  });

  it.each([
    ["Ширина, см", "64.4", "64"],
    ["Глубина, см", "51.2", "51"],
  ])("keeps the disagreement for %s without duplicating the selected result", (name, selected, alternative) => {
    const candidates = [
      { value: selected, raw_value: selected, source: "Asko", confidence: 100,
        priority: 0, reason: "Подтверждено", source_name: name, matches_current: true },
      { value: alternative, raw_value: `${alternative} см`, source: "Asko", confidence: 100,
        priority: 1, reason: "Другой источник", source_name: name, matches_current: false },
      { value: selected, raw_value: selected, source: "ChatGPT", confidence: 85,
        priority: 90, reason: "Подтверждено", source_name: name, matches_current: true },
    ];
    // The stored proposal is empty; the old UI fell back to the main donor.
    const row = value({ name, status: "conflict", value_type: "number", current_value: selected,
      final_value: selected, source_details: { candidates } });
    expect(displayedProposal(row)).toBe("");
    expect(hasPendingProposal(row)).toBe(false);
    expect(canConfirmConflictFinal(row)).toBe(true);
    expect(valueStatusLabel(row)).toBe("Конфликт");
    expect(valueStatusColor(row)).toBe("error");
    expect(matchesAttributeStatus(row, "conflict")).toBe(true);
    expect(matchesAttributeStatus(row, "suggested")).toBe(false);
    expect(row.source_details.candidates).toEqual(candidates);
    row.proposed_value = alternative;
    expect(displayedProposal(row)).toBe(alternative);
    expect(hasPendingProposal(row)).toBe(true);
    expect(canConfirmConflictFinal(row)).toBe(false);
  });

  it("hides an already selected result while keeping its manual acceptance", () => {
    const row = value({ status: "approved", current_value: "64.4", proposed_value: "64", final_value: "64" });
    expect(displayedProposal(row)).toBe("");
    expect(valueStatusLabel(row)).toBe("Принято");
    expect(hasPendingProposal(row)).toBe(false);
    expect(canConfirmConflictFinal(row)).toBe(false);
    expect(canConfirmConflictFinal(value({ final_value: "-" }))).toBe(false);
    expect(canConfirmConflictFinal(value({ final_value: "64", is_in_template: false }))).toBe(false);
    expect(canConfirmConflictFinal(value())).toBe(false);
  });

  it("does not show an additional proposal for the same value in another case", () => {
    const row = value({ status: "kept", current_value: "Встраиваемый", final_value: "Встраиваемый", proposed_value: "встраиваемый" });
    expect(attributeValuesMatch("ВСТРАИВАЕМЫЙ", "встраиваемый")).toBe(true);
    expect(hasPendingProposal(row)).toBe(false);
    expect(matchesAttributeStatus(row, "suggested")).toBe(false);
    expect(matchesAttributeStatus(row, "conflict")).toBe(false);
    expect(valueStatusColor(row)).toBe("success");
  });

  it("preserves all differences other than letter case", () => {
    expect(attributeValuesMatch("a++", "A++")).toBe(true);
    expect(attributeValuesMatch("ё", "Ё")).toBe(true);
    for (const [left, right] of [["A+", "A++"], ["60/65", "60-65"], ["A B", "A  B"], ["А", "A"], ["ё", "е"], ["ß", "SS"]]) {
      expect(attributeValuesMatch(left!, right!)).toBe(false);
      expect(hasPendingProposal(value({ status: "suggested", proposed_value: left, final_value: right }))).toBe(true);
    }
  });
});
