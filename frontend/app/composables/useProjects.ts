import { projectService } from "~/services/project.service";
import type {
  ConnectionMethod,
  ProgressPayload,
  Project,
} from "~/types/api";
import { mergeProgressState } from "~/utils/progress-state";

function mergeProject(current: Project | undefined, incoming: Project): Project {
  if (!current) return incoming;
  return {
    ...current,
    ...incoming,
    state: mergeProgressState(current.state, incoming.state),
  };
}

export function useProjects() {
  const projects = useState<Project[]>("projects", () => []);
  const progressCursor = useState<string>("projects-progress-cursor", () => "");
  const connectionMethods = useState<ConnectionMethod[]>("connection-methods", () => []);
  const loading = useState<boolean>("projects-loading", () => false);

  const upsert = (project: Project) => {
    const index = projects.value.findIndex((item) => item.id === project.id);
    if (index === -1) projects.value.push(project);
    else projects.value[index] = mergeProject(projects.value[index], project);
  };

  const load = async (summary = true) => {
    loading.value = true;
    try {
      const data = await projectService.list(summary);
      projects.value = data.projects.map((item) =>
        mergeProject(projects.value.find((current) => current.id === item.id), item),
      );
      connectionMethods.value = data.connection_methods;
      if (data.progress_cursor) progressCursor.value = data.progress_cursor;
      return data;
    } finally {
      loading.value = false;
    }
  };

  const loadProject = async (projectId: string) => {
    const data = await projectService.get(projectId);
    upsert(data.project);
    return data.project;
  };

  const mergeProgress = (payload: ProgressPayload) => {
    if (payload.cursor) progressCursor.value = payload.cursor;
    if (payload.replace_projects) {
      const currentIds = new Set(
        (payload.upsert_projects || []).map((project) => project.id),
      );
      projects.value = projects.value.filter((project) =>
        currentIds.has(project.id),
      );
    }
    for (const project of payload.upsert_projects || []) upsert(project);
    for (const incoming of payload.projects || []) {
      const project = projects.value.find((item) => item.id === incoming.id);
      if (project) project.state = mergeProgressState(project.state, incoming.state);
    }
    if (payload.removed_projects_ids?.length) {
      const removed = new Set(payload.removed_projects_ids);
      projects.value = projects.value.filter((project) => !removed.has(project.id));
    }
  };

  return {
    projects,
    progressCursor,
    connectionMethods,
    loading,
    load,
    loadProject,
    upsert,
    mergeProgress,
  };
}
