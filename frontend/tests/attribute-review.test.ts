import { describe, expect, it } from "vitest";
import type { AttributeValue } from "../app/types/attribute-assistant";
import {
  attributeValuesMatch, displayedProposal, hasPendingProposal, matchesAttributeStatus, originalValueHints,
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
    const row = value({ status: "suggested", proposed_value: "A++" });
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
    const row = value({ status: "unknown", source_details: { unknown_values: [unknown] } });
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
});


describe("attribute value letter case", () => {
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
