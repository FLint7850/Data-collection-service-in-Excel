/** Cancels superseded reads while keeping mutation requests untouched. */
export function createLatestRequestCoordinator() {
  const controllers = new Map<string, AbortController>();

  function start(key: string): AbortSignal {
    controllers.get(key)?.abort();
    const controller = new AbortController();
    controllers.set(key, controller);
    return controller.signal;
  }

  function finish(key: string, signal: AbortSignal): void {
    const controller = controllers.get(key);
    if (controller?.signal === signal) controllers.delete(key);
  }

  function cancel(key: string): void {
    controllers.get(key)?.abort();
    controllers.delete(key);
  }

  function dispose(): void {
    for (const controller of controllers.values()) controller.abort();
    controllers.clear();
  }

  return { start, finish, cancel, dispose };
}

export function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const value = error as { name?: string; cause?: { name?: string } };
  return value.name === "AbortError" || value.cause?.name === "AbortError";
}
