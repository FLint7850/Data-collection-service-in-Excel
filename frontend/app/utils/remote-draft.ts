function cloneValue<T>(value: T): T {
  if (value === undefined) return value;
  return JSON.parse(JSON.stringify(value)) as T;
}

function valuesEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function mergeRemoteDraft<T extends object, S extends object>(
  local: T,
  remote: T,
  baseline: S | null,
  current: S,
): T {
  const merged = cloneValue(remote) as Record<string, unknown>;
  if (!baseline) return merged as T;

  const localRecord = local as Record<string, unknown>;
  const baselineRecord = baseline as Record<string, unknown>;
  const currentRecord = current as Record<string, unknown>;
  for (const key of Object.keys(currentRecord)) {
    if (!valuesEqual(currentRecord[key], baselineRecord[key])) {
      merged[key] = cloneValue(localRecord[key]);
    }
  }
  return merged as T;
}
