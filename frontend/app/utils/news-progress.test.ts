import { describe, expect, it } from "vitest";
import type { NewsMonitorSummary, ProgressPayload } from "../types/api";
import { mergeNewsProgress } from "./news-progress";

const monitor: NewsMonitorSummary = {
  id: "1",
  brand_id: 1,
  primary_donor_id: "1",
  group: "Маржа",
  brand: "Bora",
  site_url: "https://example.test",
  start_urls: ["https://example.test/catalog"],
  enabled: true,
  state: {
    status: "running",
    percent: 10,
    currenturl: "",
    totalprocessed: 1,
    processed_products: 1,
    found_products: 1,
    error: "",
    elapsed_seconds: 1,
  },
};

describe("mergeNewsProgress", () => {
  it("keeps previous values while applying a small state delta", () => {
    const payload: ProgressPayload = {
      cursor: "r1:2",
      news: [{ id: "1", state: { percent: 20, found_products: 2 } }],
    };

    const result = mergeNewsProgress([monitor], payload);

    expect(result[0]?.brand).toBe("Bora");
    expect(result[0]?.state.percent).toBe(20);
    expect(result[0]?.state.found_products).toBe(2);
    expect(result[0]?.state.status).toBe("running");
  });

  it("applies cross-user additions and removals", () => {
    const added: NewsMonitorSummary = {
      ...monitor,
      id: "2",
      brand_id: 2,
      brand: "Beko",
    };
    const payload: ProgressPayload = {
      cursor: "r1:3",
      upsert_news: [added],
      removed_news_ids: ["1"],
    };

    const result = mergeNewsProgress([monitor], payload);

    expect(result.map((item) => item.id)).toEqual(["2"]);
    expect(result[0]?.brand).toBe("Beko");
  });
});
