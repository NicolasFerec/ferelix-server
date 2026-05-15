import { isTextSubtitleCodec } from "@/services/subtitles";

export interface AudioTrackOption {
    id: number;
    stream_index: number;
    language?: string;
    channels?: number;
    title?: string;
    is_default?: boolean;
}

export interface SubtitleTrackOption {
    id: number;
    stream_index: number;
    codec: string;
    language?: string;
    title?: string;
    is_forced: boolean;
    is_default: boolean;
}

export interface ResolutionOption {
    width: number;
    height: number;
    label: string;
    is_original: boolean;
}

export interface BufferedPercentage {
    start: number;
    width: number;
}

export type PlaybackMethod = "DirectPlay" | "DirectStream" | "Transcode";

export function formatTime(seconds: number): string {
    if (!seconds || Number.isNaN(seconds)) {
        return "0:00";
    }

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }

    return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

export function getAudioTrackLabel(track: AudioTrackOption): string {
    const parts: string[] = [];

    if (track.language) {
        parts.push(track.language.toUpperCase());
    }
    if (track.channels) {
        parts.push(formatChannelCount(track.channels));
    }
    if (track.title) {
        parts.push(track.title);
    }

    return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
}

export function getSubtitleTrackLabel(track: SubtitleTrackOption): string {
    const parts: string[] = [];

    if (track.language) {
        parts.push(track.language.toUpperCase());
    }
    if (track.is_forced) {
        parts.push("(Forced)");
    }
    if (track.title) {
        parts.push(track.title);
    }
    if (!isTextSubtitleCodec(track.codec)) {
        parts.push("!");
    }

    return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
}

function formatChannelCount(channels: number): string {
    if (channels === 2) {
        return "Stereo";
    }
    if (channels === 6) {
        return "5.1";
    }
    if (channels === 8) {
        return "7.1";
    }

    return `${channels}ch`;
}
