import type { OwnSite } from "../types/api";

export function cloneOwnSites(sites: OwnSite[]): OwnSite[] {
  return sites.map((site) => ({ ...site }));
}

export function mergeOwnSiteMembership(
  currentSites: OwnSite[],
  savedSites: OwnSite[],
  remoteSites: OwnSite[],
): { sites: OwnSite[]; savedSites: OwnSite[] } {
  const currentIds = new Set(
    currentSites
      .filter((site) => site.id != null)
      .map((site) => String(site.id)),
  );
  const locallyRemovedIds = new Set(
    savedSites
      .filter((site) => site.id != null && !currentIds.has(String(site.id)))
      .map((site) => String(site.id)),
  );
  const remoteIds = new Set(
    remoteSites
      .filter((site) => site.id != null)
      .map((site) => String(site.id)),
  );

  const sites = currentSites
    .filter((site) => site.id == null || remoteIds.has(String(site.id)))
    .map((site) => ({ ...site }));
  const mergedIds = new Set(
    sites
      .filter((site) => site.id != null)
      .map((site) => String(site.id)),
  );

  for (const remoteSite of remoteSites) {
    if (remoteSite.id == null) continue;
    const id = String(remoteSite.id);
    if (mergedIds.has(id) || locallyRemovedIds.has(id)) continue;
    sites.push({ ...remoteSite });
    mergedIds.add(id);
  }

  const savedById = new Map(
    savedSites
      .filter((site) => site.id != null)
      .map((site) => [String(site.id), site]),
  );
  const nextSavedSites = remoteSites.map((site) => {
    if (site.id == null) return { ...site };
    return { ...(savedById.get(String(site.id)) || site) };
  });

  return { sites, savedSites: nextSavedSites };
}
