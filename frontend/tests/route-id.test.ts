import { describe, expect, it } from "vitest";
import { normalizeBrandRouteId, normalizeProjectRouteId } from "../app/utils/route-id";

describe("route id normalization", () => {
  it("accepts supported project and brand identifiers", () => {
    expect(normalizeProjectRouteId(["123", "ignored"])).toBe("123");
    expect(normalizeProjectRouteId("a1b2c3d4e5")).toBe("a1b2c3d4e5");
    expect(normalizeBrandRouteId("18")).toBe("18");
  });

  it("rejects route placeholders and malformed ids", () => {
    expect(normalizeProjectRouteId("id")).toBe("");
    expect(normalizeBrandRouteId("0")).toBe("");
    expect(normalizeBrandRouteId("id")).toBe("");
  });
});
