function singleRouteParam(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value;
  return String(raw ?? "").trim();
}

export function normalizeProjectRouteId(value: unknown) {
  const id = singleRouteParam(value);
  return /^(?:\d+|[a-f0-9]{10})$/i.test(id) ? id : "";
}

export function normalizeBrandRouteId(value: unknown) {
  const id = singleRouteParam(value);
  return /^[1-9]\d*$/.test(id) ? id : "";
}
