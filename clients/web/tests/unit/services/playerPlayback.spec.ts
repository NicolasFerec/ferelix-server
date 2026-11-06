import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { media } from "@/api/client";
import { startPlaybackJob, waitForHlsReady } from "@/services/playerPlayback";

vi.mock("@/api/client", () => ({
    media: {
        startRemux: vi.fn(),
        stopHls: vi.fn(),
        getHlsStatus: vi.fn(),
        getHlsPlaylistUrl: () => "/playlist.m3u8",
    },
}));

beforeEach(() => vi.resetAllMocks());
afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

it("stops a job that finishes starting after the player has closed", async () => {
    let resolveJob: (job: { id: string }) => void = () => {};
    vi.mocked(media.startRemux).mockReturnValue(
        new Promise((resolve) => {
            resolveJob = resolve;
        }),
    );
    const controller = new AbortController();
    const pending = startPlaybackJob({
        mediaId: 1,
        source: { IsRemuxOnly: true },
        signal: controller.signal,
    });
    controller.abort();
    resolveJob({ id: "abandoned" });
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(media.stopHls).toHaveBeenCalledWith("abandoned");
});

it("does not keep polling once the player is closed", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(waitForHlsReady("job", undefined, 120000, controller.signal)).rejects.toMatchObject({
        name: "AbortError",
    });
    expect(media.getHlsStatus).not.toHaveBeenCalled();
});

it("fails immediately when the server is stopping the job", async () => {
    vi.mocked(media.getHlsStatus).mockResolvedValue({ status: "stopping" } as never);
    await expect(waitForHlsReady("job")).rejects.toThrow("Transcoding was cancelled");
    expect(media.getHlsStatus).toHaveBeenCalledTimes(1);
});

it("enforces the readiness deadline even while the status HTTP request is blocked", async () => {
    vi.useFakeTimers();
    vi.mocked(media.getHlsStatus).mockImplementation(
        (_id, signal) =>
            new Promise((_resolve, reject) => {
                signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
            }),
    );
    let failure: Error | undefined;
    const pending = waitForHlsReady("job", undefined, 1000).catch((error) => {
        failure = error;
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(failure?.message).toBe("Timeout waiting for transcode");
    await pending;
    expect(vi.getTimerCount()).toBe(0);
});

it("enforces the readiness deadline while the playlist HEAD request is blocked", async () => {
    vi.useFakeTimers();
    vi.mocked(media.getHlsStatus).mockResolvedValue({ status: "running" } as never);
    vi.stubGlobal(
        "fetch",
        vi.fn(
            (_url, options) =>
                new Promise((_resolve, reject) => {
                    options.signal?.addEventListener("abort", () => reject(options.signal.reason), { once: true });
                }),
        ),
    );
    let failure: Error | undefined;
    const pending = waitForHlsReady("job", undefined, 1000).catch((error) => {
        failure = error;
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(failure?.message).toBe("Timeout waiting for transcode");
    await pending;
    expect(vi.getTimerCount()).toBe(0);
});

it("cancels immediately during the 500ms polling delay", async () => {
    vi.useFakeTimers();
    vi.mocked(media.getHlsStatus).mockResolvedValue({ status: "pending" } as never);
    const controller = new AbortController();
    let failure: Error | undefined;
    const pending = waitForHlsReady("job", undefined, 120000, controller.signal).catch((error) => {
        failure = error;
    });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await vi.advanceTimersByTimeAsync(0);
    expect(failure?.name).toBe("AbortError");
    await pending;
    expect(media.getHlsStatus).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
});
