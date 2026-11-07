import { type MediaAccess, media } from "@/api/client";
import type { components } from "@/api/types";

export type TranscodingJob = components["schemas"]["TranscodingJobSchema"];

export interface TranscodeSettings {
    VideoCodec?: string;
    AudioCodec?: string;
    VideoBitrate?: number;
    AudioBitrate?: number;
    MaxWidth?: number;
    MaxHeight?: number;
    MaxFrameRate?: number;
    IsRemuxOnly?: boolean;
}

export interface StreamSource {
    PlayMethod?: string;
    TranscodingUrl?: string;
    DirectStreamUrl?: string;
    IsRemuxOnly?: boolean;
    TranscodingType?: string;
    TranscodeReasons?: string[];
    AvailableResolutions?: Array<Record<string, unknown>>;
    TranscodeSettings?: TranscodeSettings;
    TranscodingVideoCodec?: string;
    TranscodingAudioCodec?: string;
    [key: string]: unknown;
}

export interface AudioTrackLike {
    stream_index: number;
    is_default?: boolean;
}

export function defaultAudioStreamIndex(audioTracks: AudioTrackLike[]): number | undefined {
    return audioTracks.find((track) => track.is_default)?.stream_index ?? audioTracks[0]?.stream_index;
}

/** Serialize server mutations while discarding superseded user intentions. */
export function createPlaybackOperations(lifetime: AbortSignal) {
    let active: AbortController | undefined;
    let tail: Promise<unknown> = Promise.resolve();
    lifetime.addEventListener("abort", () => active?.abort(), { once: true });

    return {
        run<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
            active?.abort();
            const controller = new AbortController();
            active = controller;
            if (lifetime.aborted) controller.abort();
            const result = tail
                .catch(() => {})
                .then(async () => {
                    controller.signal.throwIfAborted();
                    return operation(controller.signal);
                });
            tail = result;
            return result;
        },
    };
}

/** A cancelled POST may have reached the server. Close the session before trying again. */
export async function playbackMutation<T>(
    request: (signal: AbortSignal) => Promise<T>,
    onUnknownOutcome?: () => void,
    maxWait = 30000,
): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(new Error("Playback request timed out")), maxWait);
    try {
        return await request(controller.signal);
    } catch (error) {
        const status = error && typeof error === "object" && "status" in error ? Number(error.status) : undefined;
        if (controller.signal.aborted || status === undefined || status >= 500) onUnknownOutcome?.();
        throw error;
    } finally {
        clearTimeout(timeout);
    }
}

export async function startPlaybackJob(options: {
    mediaId: number;
    source: StreamSource;
    videoStreamIndex?: number;
    audioStreamIndex?: number;
    subtitleStreamIndex?: number;
    startTime?: number;
    sessionId: string;
    playbackGeneration: number;
    signal?: AbortSignal;
    onUnknownOutcome?: () => void;
}): Promise<TranscodingJob> {
    options.signal?.throwIfAborted();
    const {
        mediaId,
        source,
        audioStreamIndex,
        videoStreamIndex,
        subtitleStreamIndex,
        startTime,
        sessionId,
        playbackGeneration,
    } = options;
    const settings = source.TranscodeSettings;
    const job = await playbackMutation(async (signal) => {
        const shared = {
            audioStreamIndex,
            videoStreamIndex,
            startTime: startTime || undefined,
            sessionId,
            playbackGeneration,
            signal,
        };
        if (source.TranscodingType === "remux" || source.IsRemuxOnly) return media.startRemux(mediaId, shared);
        if (source.TranscodingType === "audio-only") {
            return media.startAudioTranscode(mediaId, {
                ...shared,
                audioCodec: settings?.AudioCodec,
                audioBitrate: settings?.AudioBitrate,
            });
        }
        return media.startTranscode(mediaId, {
            ...shared,
            videoCodec: settings?.VideoCodec,
            audioCodec: settings?.AudioCodec,
            videoBitrate: settings?.VideoBitrate,
            audioBitrate: settings?.AudioBitrate,
            maxWidth: settings?.MaxWidth,
            maxHeight: settings?.MaxHeight,
            maxFrameRate: settings?.MaxFrameRate,
            subtitleStreamIndex,
        });
    }, options.onUnknownOutcome);
    if (options.signal?.aborted) {
        try {
            await media.stopHls(job.id);
        } catch (error) {
            options.onUnknownOutcome?.();
            throw error;
        }
        options.signal.throwIfAborted();
    }
    return job;
}

export async function waitForHlsReady(
    jobId: string,
    onStatus?: (status: TranscodingJob) => void,
    maxWait = 120000,
    signal?: AbortSignal,
    access?: MediaAccess,
): Promise<TranscodingJob> {
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    const timeout = setTimeout(() => controller.abort(new Error("Timeout waiting for transcode")), maxWait);
    const waitSignal = controller.signal;

    try {
        while (true) {
            waitSignal.throwIfAborted();
            const status = await media.getHlsStatus(jobId, waitSignal);
            waitSignal.throwIfAborted();
            onStatus?.(status);

            if (status.status === "failed") {
                throw new Error(status.error_message || "Transcoding failed");
            }
            if (["cancelled", "stopping"].includes(status.status)) {
                throw new Error("Transcoding was cancelled");
            }
            if (status.status === "running" || status.status === "completed") {
                try {
                    const response = await fetch(media.getHlsPlaylistUrl(jobId, access), {
                        method: "HEAD",
                        signal: waitSignal,
                    });
                    if (response.ok) return status;
                } catch {
                    waitSignal.throwIfAborted();
                }
            }
            await new Promise<void>((resolve, reject) => {
                const onAbort = () => {
                    clearTimeout(timer);
                    reject(waitSignal.reason);
                };
                const timer = setTimeout(() => {
                    waitSignal.removeEventListener("abort", onAbort);
                    resolve();
                }, 500);
                waitSignal.addEventListener("abort", onAbort, { once: true });
                if (waitSignal.aborted) onAbort();
            });
        }
    } finally {
        clearTimeout(timeout);
        signal?.removeEventListener("abort", abort);
    }
}
