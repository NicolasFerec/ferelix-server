import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getAccessToken, media, playbackSessions } from "@/api/client";
import CustomVideoPlayer from "@/components/CustomVideoPlayer.vue";
import PlayerControls from "@/components/player/PlayerControls.vue";
import PlayerStatusOverlays from "@/components/player/PlayerStatusOverlays.vue";

const hlsPlayers = vi.hoisted(
    () =>
        [] as Array<{
            source: string;
            destroyed: boolean;
            config: { xhrSetup: (xhr: XMLHttpRequest, url: string) => void };
            listeners: Map<string, (...args: unknown[]) => void>;
            recoverMediaError: () => void;
        }>,
);
vi.mock("hls.js", () => ({
    default: class {
        static isSupported = () => true;
        static Events = { MANIFEST_PARSED: "manifest", BUFFER_APPENDED: "buffer", ERROR: "error" };
        static ErrorTypes = { NETWORK_ERROR: "network", MEDIA_ERROR: "media" };
        source = "";
        destroyed = false;
        levels = [{}];
        listeners = new Map<string, (...args: unknown[]) => void>();
        constructor(public config: { xhrSetup: (xhr: XMLHttpRequest, url: string) => void }) {
            hlsPlayers.push(this);
        }
        on(event: string, callback: (...args: unknown[]) => void) {
            this.listeners.set(event, callback);
        }
        off(event: string) {
            this.listeners.delete(event);
        }
        loadSource(source: string) {
            this.source = source;
        }
        attachMedia() {
            this.listeners.get("manifest")?.();
        }
        startLoad() {}
        recoverMediaError = vi.fn();
        destroy() {
            this.destroyed = true;
        }
    },
}));
vi.mock("@/composables/useDeviceProfile", () => ({
    useDeviceProfile: () => ({ profile: { value: {} }, buildProfile: vi.fn() }),
}));
vi.mock("@/api/client", () => ({
    getAccessToken: vi.fn(() => "token"),
    media: {
        getPlaybackInfo: vi.fn(),
        startRemux: vi.fn(),
        startAudioTranscode: vi.fn(),
        startTranscode: vi.fn(),
        stopHls: vi.fn(),
        getHlsStatus: vi.fn(),
        getHlsPlaylistUrl: (id: string) => `/hls/${id}/index.m3u8`,
        getDirectStreamUrl: vi.fn(() => "/direct"),
        getSubtitleUrl: () => "/subtitle",
    },
    playbackSessions: { create: vi.fn(), heartbeat: vi.fn(), end: vi.fn() },
}));

const original = { width: 1920, height: 1080, label: "Original", is_original: true };
const smaller = { width: 1280, height: 720, label: "720p", is_original: false };
const remuxSource = {
    PlayMethod: "DirectStream",
    TranscodingUrl: "/start",
    IsRemuxOnly: true,
    TranscodingType: "remux",
    AvailableResolutions: [original, smaller],
};
const audio = [
    { id: 1, stream_index: 1, codec: "aac", language: "eng", is_default: true },
    { id: 2, stream_index: 2, codec: "aac", language: "fra" },
    { id: 3, stream_index: 3, codec: "aac", language: "deu" },
];
const imageSubtitle = { id: 4, stream_index: 4, codec: "hdmv_pgs_subtitle", is_default: false, is_forced: false };
let wrapper: VueWrapper | undefined;
const jobs = new Map<string, { id: string; status: string; start_time: number }>();
let nextJob = 0;

beforeEach(() => {
    vi.resetAllMocks();
    hlsPlayers.length = 0;
    jobs.clear();
    nextJob = 0;
    vi.mocked(getAccessToken).mockReturnValue("token");
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, text: async () => "WEBVTT\n" }));
    URL.createObjectURL = vi.fn(() => "blob:subtitle");
    URL.revokeObjectURL = vi.fn();
    vi.mocked(playbackSessions.create).mockResolvedValue({ id: "session" } as never);
    vi.mocked(playbackSessions.heartbeat).mockResolvedValue({ kicked: false } as never);
    vi.mocked(playbackSessions.end).mockResolvedValue();
    vi.mocked(media.stopHls).mockResolvedValue();
    vi.mocked(media.getPlaybackInfo).mockResolvedValue({ MediaSources: [remuxSource] } as never);
    for (const start of [media.startRemux, media.startAudioTranscode, media.startTranscode]) {
        vi.mocked(start).mockImplementation(async (_id, options) => {
            const job = { id: `job-${++nextJob}`, status: "running", start_time: options?.startTime ?? 0 };
            jobs.set(job.id, job);
            return job as never;
        });
    }
    vi.mocked(media.getHlsStatus).mockImplementation(async (id) => jobs.get(id) as never);
});

afterEach(async () => {
    wrapper?.unmount();
    wrapper = undefined;
    await flushPromises();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

async function openPlayer(extra = {}, initialAudioStreamIndex?: number, realOverlays = false) {
    wrapper = mount(CustomVideoPlayer, {
        props: {
            mediaFile: { id: 1, duration: 3600, audio_tracks: audio, subtitle_tracks: [imageSubtitle], ...extra },
            initialAudioStreamIndex,
        },
        global: { stubs: { PlayerControls: true, PlayerInfoPanel: true, PlayerStatusOverlays: !realOverlays } },
    });
    await flushPromises();
    return wrapper;
}

it("removes burned subtitles by replacing the stream when subtitles are disabled", async () => {
    const player = await openPlayer();
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("select-subtitle-track", imageSubtitle);
    await flushPromises();
    expect(media.startTranscode).toHaveBeenCalledTimes(1);
    controls.vm.$emit("select-subtitle-track", null);
    await flushPromises();
    expect(media.startRemux).toHaveBeenCalledTimes(2);
    expect(media.stopHls).toHaveBeenCalledWith("job-2");
});

it("keeps the absolute film position when switching from an offset HLS job to direct play", async () => {
    const player = await openPlayer({ user_view: { watched: false, duration_seconds: 3600, position_seconds: 600 } });
    const video = player.find("video");
    video.element.currentTime = 12;
    await video.trigger("timeupdate");
    vi.mocked(media.getPlaybackInfo).mockResolvedValue({
        MediaSources: [{ PlayMethod: "DirectPlay", DirectStreamUrl: "/direct" }],
    } as never);
    player.findComponent(PlayerControls).vm.$emit("select-resolution", original);
    await flushPromises();
    await video.trigger("loadedmetadata");
    expect(video.element.currentTime).toBe(612);
    expect(hlsPlayers.every((hls) => hls.destroyed)).toBe(true);
});

it("does not use direct fallback after the player closes during playback negotiation", async () => {
    let resolveInfo!: (value: never) => void;
    vi.mocked(media.getPlaybackInfo).mockReturnValue(
        new Promise((resolve) => {
            resolveInfo = resolve;
        }),
    );
    const player = await openPlayer();
    player.unmount();
    wrapper = undefined;
    resolveInfo({ MediaSources: [remuxSource] } as never);
    await flushPromises();
    expect(media.getDirectStreamUrl).not.toHaveBeenCalled();
    expect(media.startRemux).not.toHaveBeenCalled();
});

it("serializes rapid audio changes and only attaches the latest stream", async () => {
    const player = await openPlayer();
    let resolveJob!: (value: never) => void;
    vi.mocked(media.startRemux).mockReturnValueOnce(
        new Promise((resolve) => {
            resolveJob = resolve;
        }),
    );
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("select-audio-track", audio[1]);
    await flushPromises();
    controls.vm.$emit("select-audio-track", audio[2]);
    await flushPromises();
    expect(media.startRemux).toHaveBeenCalledTimes(2);
    const staleJob = { id: "stale-job", status: "running", start_time: 0 };
    jobs.set(staleJob.id, staleJob);
    resolveJob(staleJob as never);
    await flushPromises();
    expect(media.startRemux).toHaveBeenCalledTimes(3);
    expect(media.stopHls).toHaveBeenCalledWith("stale-job");
    expect(hlsPlayers.at(-1)?.source).toBe("/hls/job-2/index.m3u8");
    expect(hlsPlayers.some((hls) => hls.source.includes("stale-job"))).toBe(false);
});

it("uses the refreshed access token for HLS URLs containing an expired token", async () => {
    await openPlayer();
    vi.mocked(getAccessToken).mockReturnValue("refreshed-token");
    const xhr = { open: vi.fn() };
    hlsPlayers[0].config.xhrSetup(xhr as unknown as XMLHttpRequest, "/hls/job-1/segment.ts?api_key=expired-token");
    expect(xhr.open).toHaveBeenCalledOnce();
    const requestUrl = new URL(xhr.open.mock.calls[0][1]);
    expect(requestUrl.searchParams.getAll("api_key")).toEqual(["refreshed-token"]);
    xhr.open.mockClear();
    hlsPlayers[0].config.xhrSetup(xhr as unknown as XMLHttpRequest, "https://other.invalid/segment.ts");
    expect(xhr.open).not.toHaveBeenCalled();
});

it("keeps playback paused when replacing an audio stream", async () => {
    const player = await openPlayer();
    await player.find("video").trigger("pause");
    player.findComponent(PlayerControls).vm.$emit("select-audio-track", audio[1]);
    await flushPromises();
    hlsPlayers.at(-1)?.listeners.get("buffer")?.();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
});

it("ignores callbacks from destroyed HLS instances", async () => {
    const player = await openPlayer();
    const previous = hlsPlayers[0];
    player.findComponent(PlayerControls).vm.$emit("select-audio-track", audio[1]);
    await flushPromises();
    previous.listeners.get("buffer")?.();
    previous.listeners.get("error")?.("error", { fatal: true, type: "network", response: { code: 410 } });
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(media.startRemux).toHaveBeenCalledTimes(2);
});

it("still handles HLS errors after a seek within the existing transcoded range", async () => {
    const player = await openPlayer();
    const hls = hlsPlayers[0];
    vi.mocked(media.getHlsStatus).mockResolvedValue({
        id: "job-1",
        status: "running",
        start_time: 0,
        transcoded_duration: 120,
    } as never);
    player.findComponent(PlayerControls).vm.$emit("seek", 30);
    await flushPromises();
    expect(media.startRemux).toHaveBeenCalledTimes(1);
    expect(player.find("video").element.currentTime).toBe(30);
    vi.spyOn(console, "error").mockImplementation(() => {});
    hls.listeners.get("error")?.("error", { fatal: true, type: "media" });
    expect(hls.recoverMediaError).toHaveBeenCalledOnce();
});

it("transcodes an incompatible selected audio track instead of copying DTS into HLS", async () => {
    const player = await openPlayer();
    vi.mocked(media.getPlaybackInfo).mockResolvedValue({
        MediaSources: [{ ...remuxSource, PlayMethod: "Transcode", TranscodingType: "audio-only", IsRemuxOnly: false }],
    } as never);
    player.findComponent(PlayerControls).vm.$emit("select-audio-track", { ...audio[1], codec: "dts" });
    await flushPromises();
    expect(media.getPlaybackInfo).toHaveBeenLastCalledWith(
        1,
        {},
        expect.objectContaining({ audioStreamIndex: 2, enableDirectPlay: false }),
    );
    expect(media.startAudioTranscode).toHaveBeenCalledWith(1, expect.objectContaining({ audioStreamIndex: 2 }));
    expect(media.startTranscode).not.toHaveBeenCalled();
});

it("negotiates HLS for a non-default initial audio track when native track selection is unavailable", async () => {
    vi.spyOn(
        HTMLMediaElement.prototype as HTMLMediaElement & { audioTracks: unknown },
        "audioTracks",
        "get",
    ).mockReturnValue(undefined);
    await openPlayer({}, 2);
    expect(media.getPlaybackInfo).toHaveBeenCalledWith(
        1,
        {},
        expect.objectContaining({
            enableDirectPlay: false,
            audioStreamIndex: 2,
        }),
    );
});

it("does not re-add an external subtitle that was disabled during download", async () => {
    const player = await openPlayer({ user_view: { watched: false, duration_seconds: 3600, position_seconds: 600 } });
    let resolveSubtitle!: (value: unknown) => void;
    vi.mocked(fetch).mockReturnValueOnce(
        new Promise((resolve) => {
            resolveSubtitle = resolve;
        }) as never,
    );
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("select-subtitle-track", { ...imageSubtitle, codec: "subrip" });
    await flushPromises();
    controls.vm.$emit("select-subtitle-track", null);
    resolveSubtitle({ ok: true, text: async () => "WEBVTT\n" });
    await flushPromises();
    expect(player.findAll("track")).toHaveLength(0);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("stops a failed HLS startup without attaching its playlist", async () => {
    vi.mocked(media.getHlsStatus).mockResolvedValue({
        id: "job-1",
        status: "failed",
        error_message: "encoder failed",
    } as never);
    await openPlayer();
    expect(media.stopHls).toHaveBeenCalledTimes(1);
    expect(media.stopHls).toHaveBeenCalledWith("job-1");
    expect(hlsPlayers).toHaveLength(0);
    expect(media.getDirectStreamUrl).not.toHaveBeenCalled();
});

it("coalesces 20 seeks during a slow job startup into only two replacement jobs", async () => {
    const player = await openPlayer();
    let resolveJob!: (value: never) => void;
    vi.mocked(media.startRemux).mockReturnValueOnce(
        new Promise((resolve) => {
            resolveJob = resolve;
        }),
    );
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("seek", 30);
    await flushPromises();
    for (let index = 2; index <= 20; index++) {
        controls.vm.$emit("seek", index * 30);
        await flushPromises();
    }
    expect(media.startRemux).toHaveBeenCalledTimes(2); // Original + one startup still in flight.
    resolveJob({ id: "superseded-seek", status: "running", start_time: 30 } as never);
    await flushPromises();
    expect(media.startRemux).toHaveBeenCalledTimes(3); // Only the final requested seek starts next.
    expect(media.startRemux).toHaveBeenLastCalledWith(1, expect.objectContaining({ startTime: 600 }));
    expect(media.stopHls).toHaveBeenCalledWith("superseded-seek");
    expect(controls.props("displayCurrentTime")).toBe(600);
});

it("keeps controls visible while a track or quality menu is open", async () => {
    vi.useFakeTimers();
    const player = await openPlayer();
    await player.find("video").trigger("play");
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("toggle-resolution-menu");
    await vi.advanceTimersByTimeAsync(3000);
    expect(controls.props("visible")).toBe(true);
    expect(controls.props("showResolutionMenu")).toBe(true);
});

it("renegotiates pending audio selection when a seek supersedes the audio request", async () => {
    const player = await openPlayer();
    const source = { ...remuxSource, PlayMethod: "Transcode", TranscodingType: "audio-only", IsRemuxOnly: false };
    let resolveInfo!: (value: never) => void;
    vi.mocked(media.getPlaybackInfo)
        .mockReturnValueOnce(
            new Promise((resolve) => {
                resolveInfo = resolve;
            }),
        )
        .mockResolvedValue({ MediaSources: [source] } as never);
    vi.mocked(media.getHlsStatus).mockResolvedValue({
        id: "job-1",
        status: "running",
        start_time: 0,
        transcoded_duration: 120,
    } as never);
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("select-audio-track", { ...audio[1], codec: "dts" });
    await flushPromises();
    controls.vm.$emit("seek", 30);
    resolveInfo({ MediaSources: [source] } as never);
    await flushPromises();
    expect(media.getPlaybackInfo).toHaveBeenCalledTimes(3);
    expect(media.getPlaybackInfo).toHaveBeenLastCalledWith(1, {}, expect.objectContaining({ audioStreamIndex: 2 }));
    expect(media.startAudioTranscode).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ audioStreamIndex: 2, startTime: 30 }),
    );
});

it("preserves a pending quality selection when seeking before negotiation completes", async () => {
    const player = await openPlayer();
    const source = {
        ...remuxSource,
        PlayMethod: "Transcode",
        TranscodingType: "full",
        IsRemuxOnly: false,
        TranscodeSettings: { VideoCodec: "h264", MaxWidth: 1280, MaxHeight: 720 },
    };
    let resolveInfo!: (value: never) => void;
    vi.mocked(media.getPlaybackInfo)
        .mockReturnValueOnce(
            new Promise((resolve) => {
                resolveInfo = resolve;
            }),
        )
        .mockResolvedValue({ MediaSources: [source] } as never);
    const controls = player.findComponent(PlayerControls);
    controls.vm.$emit("select-resolution", smaller);
    await flushPromises();
    controls.vm.$emit("seek", 300);
    resolveInfo({ MediaSources: [source] } as never);
    await flushPromises();
    expect(media.getPlaybackInfo).toHaveBeenLastCalledWith(
        1,
        {},
        expect.objectContaining({ requestedResolution: expect.objectContaining({ width: 1280, height: 720 }) }),
    );
    expect(media.startTranscode).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ maxWidth: 1280, maxHeight: 720, startTime: 300 }),
    );
    expect(controls.props("selectedResolutionLabel")).toBe("720p");
});

it("encodes video when burning subtitles into a copy-only remux plan", async () => {
    vi.mocked(media.getPlaybackInfo).mockResolvedValue({
        MediaSources: [{ ...remuxSource, TranscodeSettings: { VideoCodec: "copy", AudioCodec: "copy" } }],
    } as never);
    const player = await openPlayer();
    player.findComponent(PlayerControls).vm.$emit("select-subtitle-track", imageSubtitle);
    await flushPromises();
    expect(media.startTranscode).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ videoCodec: "h264", subtitleStreamIndex: 4 }),
    );
});

it("allows closing the player from a fatal error overlay", async () => {
    vi.mocked(media.getHlsStatus).mockResolvedValue({ status: "failed", error_message: "encoder failed" } as never);
    const player = await openPlayer({}, undefined, true);
    const closeButton = player
        .findComponent(PlayerStatusOverlays)
        .findAll("button")
        .find((button) => button.text() === "player.close");
    expect(closeButton).toBeDefined();
    await closeButton?.trigger("click");
    expect(player.emitted("close")).toHaveLength(1);
});
