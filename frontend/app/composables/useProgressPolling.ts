export function useProgressPolling(
  callback: () => Promise<void> | void,
  enabled: Ref<boolean> | ComputedRef<boolean> = ref(true),
  intervalMs?: number,
) {
  const config = useRuntimeConfig();
  const inFlight = ref(false);
  let timer: ReturnType<typeof setInterval> | undefined;

  const run = async () => {
    if (
      !enabled.value ||
      inFlight.value ||
      (import.meta.client && document.visibilityState === "hidden")
    ) return;
    inFlight.value = true;
    try {
      await callback();
    } finally {
      inFlight.value = false;
    }
  };

  const stop = () => {
    if (timer) clearInterval(timer);
    timer = undefined;
  };

  const start = () => {
    stop();
    if (!enabled.value) return;
    void run();
    const interval = Math.max(
      500,
      Math.min(
        Number(intervalMs || config.public.progressIntervalMs || 2000),
        30000,
      ),
    );
    timer = setInterval(run, interval);
  };

  const handleVisibilityChange = () => {
    if (document.visibilityState === "visible") void run();
  };

  onMounted(() => {
    start();
    document.addEventListener("visibilitychange", handleVisibilityChange);
  });
  onBeforeUnmount(() => {
    stop();
    document.removeEventListener("visibilitychange", handleVisibilityChange);
  });
  watch(enabled, start);

  return { inFlight, refresh: run, stop };
}
