import { describe, expect, it } from "vitest";
import { mergeProgressState } from "../app/utils/progress-state";

describe("mergeProgressState", () => {
  it("keeps non-zero values during a transient empty update of the same run", () => {
    const previous = {
      status: "running",
      started_at: "2026-07-31T12:00:00+03:00",
      percent: 45,
      found_products: 12,
      active_urls: ["https://example.test/product"],
    };
    const incoming = {
      status: "running",
      started_at: "2026-07-31T12:00:00+03:00",
      percent: 0,
      found_products: 0,
      active_urls: [],
    };

    expect(mergeProgressState(previous, incoming)).toEqual(previous);
  });

  it("accepts zeroes when a run has completed", () => {
    const result = mergeProgressState(
      { status: "running", percent: 50, found_products: 10 },
      { status: "completed", percent: 0, found_products: 0 },
    );

    expect(result.percent).toBe(0);
    expect(result.found_products).toBe(0);
  });
});
