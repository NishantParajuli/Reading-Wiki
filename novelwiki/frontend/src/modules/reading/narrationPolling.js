const TERMINAL_JOB_STATUSES = new Set(["done", "failed", "canceled"]);

function isRetryable(error) {
  const status = Number(error && error.status);
  return !Number.isFinite(status) || status >= 500 || status === 408 || status === 429;
}

/**
 * Poll one durable narration job without overlapping requests.
 *
 * Network and temporary server failures back off and retry because the job continues
 * independently on the server. Authentication/authorization/not-found responses remain
 * terminal client errors. The returned function cancels both a scheduled poll and the
 * callbacks from an already in-flight request.
 */
export function pollNarrationJob({
  jobId,
  loadJob,
  onProgress = () => {},
  onTerminal = () => {},
  onRetry = () => {},
  onError = () => {},
  delayMs = 1500,
  maxDelayMs = 10000,
}) {
  let stopped = false;
  let timer = null;
  let failures = 0;

  const stop = () => {
    stopped = true;
    if (timer != null) clearTimeout(timer);
    timer = null;
  };

  const schedule = (delay) => {
    if (stopped) return;
    timer = setTimeout(run, delay);
  };

  const run = async () => {
    timer = null;
    if (stopped) return;
    try {
      const job = await loadJob(jobId);
      if (stopped) return;
      failures = 0;
      onProgress(job);
      if (TERMINAL_JOB_STATUSES.has(job.status)) {
        stop();
        await onTerminal(job);
        return;
      }
      schedule(delayMs);
    } catch (error) {
      if (stopped) return;
      if (!isRetryable(error)) {
        stop();
        onError(error);
        return;
      }
      failures += 1;
      onRetry(error, failures);
      const retryDelay = Math.min(maxDelayMs, delayMs * (2 ** (failures - 1)));
      schedule(retryDelay);
    }
  };

  schedule(delayMs);
  return stop;
}
