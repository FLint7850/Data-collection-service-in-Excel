import { describe, expect, it } from "vitest";
import type { ProgressPayload, Project } from "../app/types/api";
import { mergeProjectsProgress } from "../app/utils/projects-progress";

const project: Project = {
  id: "1",
  name: "Old name",
  start_urls: ["https://old.example.test"],
  thread_count: 4,
  exclusions: [],
  product_url_filters: [],
  product_url_exclusions: [],
  extraction_rules: {},
  state: {
    status: "idle",
    percent: 0,
    currenturl: "",
    totalprocessed: 0,
    processed_products: 0,
    found_products: 0,
    error: "",
    elapsed_seconds: 0,
  },
  auto_cleanup: false,
  connection_method: "requests",
  auto_connection_fallback: true,
  persist_profile: false,
};

describe("mergeProjectsProgress", () => {
  it("applies full details for the active cross-user form", () => {
    const detail: Project = {
      ...project,
      name: "New name",
      start_urls: ["https://new.example.test"],
      thread_count: 9,
      exclusions: ["sale"],
    };
    const payload: ProgressPayload = {
      cursor: "r1:2",
      project_detail: detail,
    };

    const result = mergeProjectsProgress([project], payload);

    expect(result[0]?.name).toBe("New name");
    expect(result[0]?.start_urls).toEqual(["https://new.example.test"]);
    expect(result[0]?.thread_count).toBe(9);
    expect(result[0]?.exclusions).toEqual(["sale"]);
  });
});
