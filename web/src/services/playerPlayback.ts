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
    const startedAt = Date.now();

    while (Date.now() - startedAt < maxWait) {
        signal?.throwIfAborted();
        const status = await media.getHlsStatus(jobId);
        signal?.throwIfAborted();
        onStatus?.(status);

        if (status.status === "failed") {
            throw new Error(status.error_message || "Transcoding failed");
        }
        if (status.status === "cancelled") {
            throw new Error("Transcoding was cancelled");
        }
        if (status.status === "running" || status.status === "completed") {
            try {
                const response = await fetch(media.getHlsPlaylistUrl(jobId), { method: "HEAD", signal });
                if (response.ok) {
                    return status;
                }
            } catch {
                // Playlist route blocks briefly server-side; keep polling if the request is interrupted.
            }
        }

        await new Promise((resolve) => setTimeout(resolve, 500));
    }

    throw new Error("Timeout waiting for transcode");
}
