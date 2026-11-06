import { media } from "@/api/client";
import type { components } from "@/api/types";

export type TranscodingJob = components["schemas"]["TranscodingJobSchema"];

export interface TranscodeSettings {
    VideoCodec?: string;
    AudioCodec?: string;
    VideoBitrate?: number;
    AudioBitrate?: number;
    MaxWidth?: number;
    MaxHeight?: number;
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

export async function startPlaybackJob(options: {
    mediaId: number;
    source: StreamSource;
    audioStreamIndex?: number;
    subtitleStreamIndex?: number;
    startTime?: number;
    sessionId?: string | null;
    signal?: AbortSignal;
}): Promise<TranscodingJob> {
    const { mediaId, source, audioStreamIndex, subtitleStreamIndex, startTime, sessionId } = options;
    options.signal?.throwIfAborted();
    let job: TranscodingJob;
    const settings = source.TranscodeSettings;
    const transcodingType = source.TranscodingType || "full";

    if (transcodingType === "remux" || source.IsRemuxOnly) {
        job = await media.startRemux(mediaId, {
            audioStreamIndex,
            startTime: startTime || undefined,
            sessionId,
        });
    } else if (transcodingType === "audio-only") {
        job = await media.startAudioTranscode(mediaId, {
            audioCodec: settings?.AudioCodec,
            audioBitrate: settings?.AudioBitrate,
            audioStreamIndex,
            startTime: startTime || undefined,
            sessionId,
        });
    } else {
        job = await media.startTranscode(mediaId, {
            videoCodec: settings?.VideoCodec,
            audioCodec: settings?.AudioCodec,
            videoBitrate: settings?.VideoBitrate,
            audioBitrate: settings?.AudioBitrate,
            maxWidth: settings?.MaxWidth,
            maxHeight: settings?.MaxHeight,
            audioStreamIndex,
            subtitleStreamIndex,
            startTime: startTime || undefined,
            sessionId,
        });
    }
    if (options.signal?.aborted) {
        await media.stopHls(job.id);
        options.signal.throwIfAborted();
    }
    return job;
}

export async function waitForHlsReady(
    jobId: string,
    onStatus?: (status: TranscodingJob) => void,
    maxWait = 120000,
    signal?: AbortSignal,
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
                    const response = await fetch(media.getHlsPlaylistUrl(jobId), {
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
