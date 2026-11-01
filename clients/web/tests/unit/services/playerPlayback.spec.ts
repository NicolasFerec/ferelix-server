import { beforeEach, expect, it, vi } from "vitest";
import { media } from "@/api/client";
import { startPlaybackJob, waitForHlsReady } from "@/services/playerPlayback";

vi.mock("@/api/client", () => ({
    media: {
        startRemux: vi.fn(),
        stopHls: vi.fn(),
        getHlsStatus: vi.fn(),
    },
}));

beforeEach(() => vi.resetAllMocks());

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
