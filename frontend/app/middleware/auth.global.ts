import { authService } from "~/services/auth.service";
import type { AuthSession } from "~/types/api";

export default defineNuxtRouteMiddleware(async (to) => {
  const session = useState<AuthSession | null>("auth-session", () => null);

  if (import.meta.server) return;

  const previousUsername = session.value?.authenticated ? session.value.username : "";
  try {
    session.value = await authService.session();
  } catch {
    session.value = { authenticated: false, username: "" };
  }
  const currentUsername = session.value.authenticated ? session.value.username : "";
  if (previousUsername && previousUsername !== currentUsername) clearDomainCache();

  if (to.path === "/login") {
    if (session.value.authenticated) return navigateTo("/projects");
    return;
  }

  if (!session.value.authenticated) {
    return navigateTo({ path: "/login", query: { redirect: to.fullPath } });
  }
});
