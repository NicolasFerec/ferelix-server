import { afterEach, describe, expect, it, vi } from "vitest";
import { probeHevcPlayback } from "@/services/deviceProfile";

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe("HEVC HLS capabilities", () => {
    it("requires fragmented MP4 MediaSource support", async () => {
        const decodingInfo = vi.fn();
        vi.stubGlobal("MediaSource", { isTypeSupported: () => false });
        vi.stubGlobal("navigator", { mediaCapabilities: { decodingInfo } });
        expect(await probeHevcPlayback()).toEqual({ main: false, main10: false });
        expect(decodingInfo).not.toHaveBeenCalled();
    });

    it("distinguishes Main from Main 10 and checks 4K decoding", async () => {
        vi.stubGlobal("MediaSource", { isTypeSupported: () => true });
        const decodingInfo = vi.fn(async (config: MediaDecodingConfiguration) => ({
            supported: config.video?.contentType.includes(".1.6.") ?? false,
        }));
        vi.stubGlobal("navigator", { mediaCapabilities: { decodingInfo } });
        expect(await probeHevcPlayback()).toEqual({ main: true, main10: false });
        expect(decodingInfo).toHaveBeenCalledWith(
            expect.objectContaining({
                type: "media-source",
                video: expect.objectContaining({ width: 3840, height: 2160 }),
            }),
        );
    });

    it("tries hev1 when hvc1 is unavailable", async () => {
        vi.stubGlobal("MediaSource", { isTypeSupported: (type: string) => type.includes("hev1") });
        vi.stubGlobal("navigator", { mediaCapabilities: { decodingInfo: async () => ({ supported: true }) } });
        expect(await probeHevcPlayback()).toEqual({ main: true, main10: true });
    });

    it("preserves native HLS playback when MediaSource is unavailable", async () => {
        vi.stubGlobal("MediaSource", undefined);
        vi.spyOn(HTMLMediaElement.prototype, "canPlayType").mockReturnValue("probably");
        const decodingInfo = vi.fn(async () => ({ supported: true }));
        vi.stubGlobal("navigator", { mediaCapabilities: { decodingInfo } });
        expect(await probeHevcPlayback()).toEqual({ main: true, main10: true });
        expect(decodingInfo).toHaveBeenCalledWith(expect.objectContaining({ type: "file" }));
    });

    it("keeps unsupported or rejected decoders on the transcode path", async () => {
        vi.stubGlobal("MediaSource", { isTypeSupported: () => true });
        vi.stubGlobal("navigator", {
            mediaCapabilities: {
                decodingInfo: async () => {
                    throw new Error("unsupported");
                },
            },
        });
        expect(await probeHevcPlayback()).toEqual({ main: false, main10: false });
    });
});
