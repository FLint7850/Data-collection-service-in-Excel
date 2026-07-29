import type { AuthSession } from "~/types/api";

export const authService = {
  session: () => $fetch<AuthSession>("/api/auth/session"),
  login: (username: string, password: string) =>
    $fetch<{ authenticated: boolean; username: string }>("/api/auth/login", {
      method: "POST",
      body: { username, password },
    }),
  logout: () =>
    $fetch<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
    }),
};
