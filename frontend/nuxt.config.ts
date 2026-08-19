import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { loadEnvFile } from "node:process";

const rootEnvPath = resolve(process.cwd(), "../.env");
if (existsSync(rootEnvPath)) {
  loadEnvFile(rootEnvPath);
}

export default defineNuxtConfig({
  compatibilityDate: "2026-07-29",
  devtools: { enabled: process.env.NODE_ENV !== "production" },
  modules: ["@nuxt/ui", "@nuxt/icon"],
  css: ["~/assets/css/main.css"],
  app: {
    head: {
      htmlAttrs: { lang: "ru", class: "dark" },
      title: "Excel Data Collector",
      meta: [
        {
          name: "description",
          content:
            "Сбор каталогов, мониторинг новинок и сравнение товарных фидов.",
        },
        { name: "theme-color", content: "#0b0e0d" },
      ],
      link: [{ rel: "icon", type: "image/svg+xml", href: "/logo.svg" }],
    },
  },
  runtimeConfig: {
    backendUrl:
      process.env.NUXT_BACKEND_URL ||
      process.env.BACKEND_URL ||
      "http://127.0.0.1:5000",
    public: {
      progressIntervalMs: Number(process.env.NUXT_PUBLIC_PROGRESS_INTERVAL_MS || 2000),
    },
  },
  nitro: {
    preset: "node-server",
  },
  icon: {
    provider: "none",
    clientBundle: {
      scan: true,
    },
  },
  colorMode: {
    preference: "dark",
    fallback: "dark",
    classSuffix: "",
  },
  typescript: {
    typeCheck: true,
    strict: true,
  },
});
