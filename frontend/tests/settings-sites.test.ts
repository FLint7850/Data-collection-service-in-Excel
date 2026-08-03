import { describe, expect, it } from "vitest";
import type { OwnSite } from "../app/types/api";
import {
  cloneOwnSites,
  mergeOwnSiteMembership,
} from "../app/utils/settings-sites";

const first: OwnSite = {
  id: 1,
  name: "Основной сайт",
  feed_url: "https://example.test/feed.xml",
  feed_generate_url: "https://example.test/generate",
};

describe("settings own-site drafts", () => {
  it("keeps the saved snapshot independent from form mutations", () => {
    const sites = cloneOwnSites([first]);
    const savedSites = cloneOwnSites(sites);

    sites.push({
      name: "Новый сайт",
      feed_url: "https://new.example/feed.xml",
      feed_generate_url: "",
    });

    expect(savedSites).toEqual([first]);
    expect(sites).toHaveLength(2);
  });

  it("does not restore a locally removed site during polling", () => {
    const result = mergeOwnSiteMembership([], [first], [first]);

    expect(result.sites).toEqual([]);
    expect(result.savedSites).toEqual([first]);
  });

  it("applies remote additions and deletions without changing local fields", () => {
    const locallyEdited = { ...first, name: "Черновик названия" };
    const added: OwnSite = {
      id: 2,
      name: "Новый удалённый сайт",
      feed_url: "https://second.example/feed.xml",
      feed_generate_url: "",
    };
    const result = mergeOwnSiteMembership(
      [locallyEdited],
      [first],
      [{ ...first, name: "Имя другого пользователя" }, added],
    );

    expect(result.sites).toEqual([locallyEdited, added]);

    const afterRemoteDeletion = mergeOwnSiteMembership(
      result.sites,
      result.savedSites,
      [added],
    );
    expect(afterRemoteDeletion.sites).toEqual([added]);
  });
});
