export default defineEventHandler((event) => {
  const config = useRuntimeConfig(event);
  const search = getRequestURL(event).search;
  return proxyRequest(event, `${config.backendUrl}/progress${search}`);
});
