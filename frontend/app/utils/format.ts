export function formatDuration(value?: number | null): string {
  const seconds = Math.max(0, Math.round(Number(value || 0)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return [hours, minutes, rest].map((item) => String(item).padStart(2, "0")).join(":");
}

export function formatFileSize(value?: number | null): string {
  const bytes = Math.max(0, Number(value || 0));
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / 1024 ** index;
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

export function formatDateTime(value?: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

export function hostFromUrl(value?: string): string {
  if (!value) return "Сайт не указан";
  try {
    return new URL(value).host.replace(/^www\./, "");
  } catch {
    return value;
  }
}

type ErrorRecord = Record<string, unknown>;

function asErrorRecord(value: unknown): ErrorRecord | undefined {
  return typeof value === "object" && value !== null ? (value as ErrorRecord) : undefined;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function errorStatusCode(error: unknown): number | undefined {
  const root = asErrorRecord(error);
  const data = asErrorRecord(root?.data);
  const response = asErrorRecord(root?.response);
  const candidates = [
    root?.statusCode,
    root?.status,
    data?.statusCode,
    data?.status,
    response?.statusCode,
    response?.status,
  ];

  for (const candidate of candidates) {
    const statusCode = Number(candidate);
    if (Number.isInteger(statusCode) && statusCode >= 100 && statusCode <= 599) {
      return statusCode;
    }
  }

  return undefined;
}

export function errorMessage(error: unknown, fallback = "Не удалось выполнить действие"): string {
  const root = asErrorRecord(error);
  const data = asErrorRecord(root?.data);

  for (const candidate of [data?.error, data?.message, data?.statusMessage, root?.message]) {
    const message = nonEmptyString(candidate);
    if (message) return message;
  }

  return fallback;
}

export function scanStatusLabel(status?: string): string {
  const labels: Record<string, string> = {
    idle: "Ожидание",
    queued: "В очереди",
    running: "Выполняется",
    pausing: "Завершение",
    paused: "На паузе",
    partial: "Результат готов",
    stopping: "Остановка",
    stopped: "Остановлено",
    complete: "Завершено",
    completed: "Завершено",
    error: "Ошибка",
  };
  return labels[status || "idle"] || status || "Ожидание";
}

export function scanStatusColor(
  status?: string,
): "neutral" | "primary" | "success" | "warning" | "error" | "info" {
  if (["running", "queued"].includes(status || "")) return "primary";
  if (["complete", "completed", "partial"].includes(status || "")) return "success";
  if (["paused", "pausing", "stopping", "stopped"].includes(status || "")) return "warning";
  if (status === "error") return "error";
  return "neutral";
}
