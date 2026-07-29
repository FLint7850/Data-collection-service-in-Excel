import { describe, expect, it } from "vitest";
import {
  normalizeBrandRouteId,
  normalizeProjectRouteId,
} from "../app/utils/route-id";

describe("dynamic route identifiers", () => {
  it("accepts database and generated project identifiers", () => {
    expect(normalizeProjectRouteId("42")).toBe("42");
    expect(normalizeProjectRouteId("a1b2c3d4e5")).toBe("a1b2c3d4e5");
  });

  it("rejects project placeholders and malformed identifiers", () => {
    expect(normalizeProjectRouteId("id")).toBe("");
    expect(normalizeProjectRouteId("project/42")).toBe("");
    expect(normalizeProjectRouteId("")).toBe("");
  });

  it("only accepts positive numeric brand identifiers", () => {
    expect(normalizeBrandRouteId("7")).toBe("7");
    expect(normalizeBrandRouteId("id")).toBe("");
    expect(normalizeBrandRouteId("0")).toBe("");
    expect(normalizeBrandRouteId("-1")).toBe("");
  });
});
