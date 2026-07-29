export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event);
  const path = getRouterParam(event, "path") || "";
  const search = getRequestURL(event).search;
  return proxyRequest(event, `${config.backendUrl}/api/${path}${search}`);
});
