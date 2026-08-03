import type { ProgressPayload, Project } from "../types/api";
import { mergeProgressState } from "./progress-state";

export function mergeProject(
  current: Project | undefined,
  incoming: Project,
): Project {
  if (!current) return incoming;
  return {
    ...current,
    ...incoming,
    state: mergeProgressState(current.state, incoming.state),
  };
}

export function mergeProjectsProgress(
  current: Project[],
  payload: ProgressPayload,
): Project[] {
  let projects = [...current];
  if (payload.replace_projects) {
    const currentIds = new Set(
      (payload.upsert_projects || []).map((project) => project.id),
    );
    projects = projects.filter((project) => currentIds.has(project.id));
  }

  const upsert = (incoming: Project) => {
    const index = projects.findIndex((project) => project.id === incoming.id);
    if (index === -1) projects.push(incoming);
    else projects[index] = mergeProject(projects[index], incoming);
  };
  for (const project of payload.upsert_projects || []) upsert(project);

  for (const incoming of payload.projects || []) {
    const project = projects.find((item) => item.id === incoming.id);
    if (project) {
      project.state = mergeProgressState(project.state, incoming.state);
    }
  }

  if (payload.removed_projects_ids?.length) {
    const removed = new Set(payload.removed_projects_ids);
    projects = projects.filter((project) => !removed.has(project.id));
  }
  return projects;
}
