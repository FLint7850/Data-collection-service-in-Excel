import { describe, expect, it } from "vitest";
import { mergeRemoteDraft } from "../app/utils/remote-draft";

describe("mergeRemoteDraft", () => {
  it("updates clean fields and preserves unsaved local fields", () => {
    const baseline = {
      name: "Old name",
      start_urls: ["https://old.example.test"],
    };
    const local = {
      ...baseline,
      name: "Unsaved local name",
      state: { status: "idle" },
    };
    const remote = {
      name: "Remote name",
      start_urls: ["https://new.example.test"],
      state: { status: "running" },
    };
    const current = {
      name: local.name,
      start_urls: local.start_urls,
    };

    const result = mergeRemoteDraft(local, remote, baseline, current);

    expect(result.name).toBe("Unsaved local name");
    expect(result.start_urls).toEqual(["https://new.example.test"]);
    expect(result.state.status).toBe("running");
  });
});
