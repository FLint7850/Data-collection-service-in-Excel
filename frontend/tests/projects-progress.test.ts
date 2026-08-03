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
  it("updates card fields without replacing stored form details", () => {
    const summary = {
      id: project.id,
      name: "New name",
      thread_count: 9,
      start_urls_count: 3,
      connection_method: "requests",
      state: { status: "running", percent: 25 },
    } as Project;
    const payload: ProgressPayload = {
      cursor: "r1:2",
      upsert_projects: [summary],
    };

    const result = mergeProjectsProgress([project], payload);

    expect(result[0]?.name).toBe("New name");
    expect(result[0]?.start_urls).toEqual(["https://old.example.test"]);
    expect(result[0]?.thread_count).toBe(9);
    expect(result[0]?.exclusions).toEqual([]);
    expect(result[0]?.state.status).toBe("running");
  });
});
