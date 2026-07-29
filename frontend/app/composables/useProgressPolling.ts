export function useProgressPolling(
  callback: () => Promise<void> | void,
  enabled: Ref<boolean> | ComputedRef<boolean> = ref(true),
) {
  const config = useRuntimeConfig();
  const inFlight = ref(false);
  let timer: ReturnType<typeof setInterval> | undefined;

  const run = async () => {
    if (!enabled.value || inFlight.value) return;
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
      Math.min(Number(config.public.progressIntervalMs || 2000), 30000),
    );
    timer = setInterval(run, interval);
  };

  onMounted(start);
  onBeforeUnmount(stop);
  watch(enabled, start);

  return { inFlight, refresh: run, stop };
}
