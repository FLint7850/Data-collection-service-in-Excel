import { projectService } from "~/services/project.service";
import type {
  ConnectionMethod,
  ProgressPayload,
  Project,
} from "~/types/api";
import { mergeProject, mergeProjectsProgress } from "~/utils/projects-progress";

export function useProjects() {
  const projects = useState<Project[]>("projects", () => []);
  const progressCursor = useState<string>("projects-progress-cursor", () => "");
  const connectionMethods = useState<ConnectionMethod[]>("connection-methods", () => []);
  const loading = useState<boolean>("projects-loading", () => true);
  const loaded = useState<boolean>("projects-loaded", () => false);

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
      loaded.value = true;
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
    projects.value = mergeProjectsProgress(projects.value, payload);
  };

  return {
    projects,
    progressCursor,
    connectionMethods,
    loading,
    loaded,
    load,
    loadProject,
    upsert,
    mergeProgress,
  };
}
