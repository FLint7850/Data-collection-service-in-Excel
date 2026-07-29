import { projectService } from "~/services/project.service";
import type {
  ConnectionMethod,
  ProgressPayload,
  Project,
} from "~/types/api";

function mergeProject(current: Project | undefined, incoming: Project): Project {
  if (!current) return incoming;
  return {
    ...current,
    ...incoming,
    state: { ...current.state, ...incoming.state },
  };
}

export function useProjects() {
  const projects = useState<Project[]>("projects", () => []);
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
    if (payload.connection_methods) connectionMethods.value = payload.connection_methods;
    if (!payload.projects) return;
    for (const project of payload.projects) upsert(project);
  };

  return {
    projects,
    connectionMethods,
    loading,
    load,
    loadProject,
    upsert,
    mergeProgress,
  };
}
