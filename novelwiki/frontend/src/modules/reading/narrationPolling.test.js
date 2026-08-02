import { afterEach, describe, expect, it, vi } from "vitest";

import { pollNarrationJob } from "./narrationPolling.js";

function deferred() {
  let resolve;
  const promise = new Promise((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("narration job polling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps one request in flight and retries a transient fetch failure", async () => {
    vi.useFakeTimers();
    const first = deferred();
    const loadJob = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ id: 33, status: "done" });
    const onRetry = vi.fn();
    const onTerminal = vi.fn();

    pollNarrationJob({ jobId: 33, loadJob, onRetry, onTerminal });

    await vi.advanceTimersByTimeAsync(1500);
    expect(loadJob).toHaveBeenCalledTimes(1);

    // No interval can enqueue overlapping polls while the first request is pending.
    await vi.advanceTimersByTimeAsync(15000);
    expect(loadJob).toHaveBeenCalledTimes(1);

    first.resolve({ id: 33, status: "generating" });
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1500);
    expect(loadJob).toHaveBeenCalledTimes(2);
    expect(onRetry).toHaveBeenCalledWith(expect.any(TypeError), 1);

    await vi.advanceTimersByTimeAsync(1500);
    expect(loadJob).toHaveBeenCalledTimes(3);
    expect(onTerminal).toHaveBeenCalledWith({ id: 33, status: "done" });
  });

  it("stops on a permanent job lookup error", async () => {
    vi.useFakeTimers();
    const error = Object.assign(new Error("Job not found."), { status: 404 });
    const loadJob = vi.fn().mockRejectedValue(error);
    const onError = vi.fn();
    const onRetry = vi.fn();

    pollNarrationJob({ jobId: 44, loadJob, onError, onRetry });
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(30000);

    expect(loadJob).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(error);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("ignores an in-flight result after cancellation", async () => {
    vi.useFakeTimers();
    const pending = deferred();
    const onProgress = vi.fn();
    const stop = pollNarrationJob({
      jobId: 55,
      loadJob: () => pending.promise,
      onProgress,
    });

    await vi.advanceTimersByTimeAsync(1500);
    stop();
    pending.resolve({ id: 55, status: "generating" });
    await Promise.resolve();

    expect(onProgress).not.toHaveBeenCalled();
  });
});
