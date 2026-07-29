import { authService } from "~/services/auth.service";
import type { AuthSession } from "~/types/api";

export default defineNuxtRouteMiddleware(async (to) => {
  const session = useState<AuthSession | null>("auth-session", () => null);

  if (import.meta.server) return;

  try {
    session.value = await authService.session();
  } catch {
    session.value = { authenticated: false, username: "" };
  }

  if (to.path === "/login") {
    if (session.value.authenticated) return navigateTo("/projects");
    return;
  }

  if (!session.value.authenticated) {
    return navigateTo({ path: "/login", query: { redirect: to.fullPath } });
  }
});
