import type { ConnectionMethod, NewsWorkspaceData, Project } from "~/types/api";

export function clearDomainCache() {
  useState<Project[]>("projects").value = [];
  useState<string>("projects-progress-cursor").value = "";
  useState<ConnectionMethod[]>("connection-methods").value = [];
  useState<boolean>("projects-loading").value = true;
  useState<boolean>("projects-loaded").value = false;

  useState<NewsWorkspaceData | null>("news-workspace").value = null;
  useState<string>("news-progress-cursor").value = "";
  useState<boolean>("news-loading").value = true;
  useState<boolean>("news-loaded").value = false;
}
