export interface SubtitleTrackLike {
    stream_index: number;
    codec?: string;
    language?: string;
    title?: string;
    is_forced?: boolean;
}

export const TEXT_SUBTITLE_CODECS = new Set(["subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"]);

export function isTextSubtitleCodec(codec?: string): boolean {
    return TEXT_SUBTITLE_CODECS.has(codec?.toLowerCase() || "");
}

export function adjustWebVttForOffset(vttContent: string, offset: number): string {
    if (offset <= 0) {
        return vttContent;
    }

    const cueBlocks = vttContent.split(/\n\n+/);
    const adjustedBlocks: string[] = [];
    const startsWithHeader = cueBlocks[0]?.includes("WEBVTT");
    if (startsWithHeader) {
        adjustedBlocks.push(cueBlocks[0]);
    }

    for (let i = startsWithHeader ? 1 : 0; i < cueBlocks.length; i++) {
        const block = cueBlocks[i];
        if (!block) {
            continue;
        }

        let timestampMatch = block.match(/(\d{2,}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2}\.\d{3})/);
        let isShortFormat = false;

        if (!timestampMatch) {
            timestampMatch = block.match(/(\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2}:\d{2}\.\d{3})/);
            isShortFormat = true;
        }

        if (!timestampMatch) {
            adjustedBlocks.push(block);
            continue;
        }

        const startSeconds = timeToSeconds(timestampMatch[1], isShortFormat);
        const endSeconds = timeToSeconds(timestampMatch[2], isShortFormat);

        if (endSeconds <= offset) {
            continue;
        }

        const adjustedStart = Math.max(0, startSeconds - offset);
        const adjustedEnd = endSeconds - offset;
        const adjustedTimestamp = `${secondsToTime(adjustedStart, isShortFormat)} --> ${secondsToTime(adjustedEnd, isShortFormat)}`;
        adjustedBlocks.push(block.replace(timestampMatch[0], adjustedTimestamp));
    }

    return adjustedBlocks.join("\n\n");
}

export function timeToSeconds(time: string, isShortFormat = false): number {
    const parts = time.split(":");
    if (isShortFormat || parts.length === 2) {
        const minutes = Number.parseInt(parts[0], 10);
        const [secondsText, millisecondsText] = parts[1].split(".");
        return minutes * 60 + Number.parseInt(secondsText, 10) + Number.parseInt(millisecondsText, 10) / 1000;
    }

    const hours = Number.parseInt(parts[0], 10);
    const minutes = Number.parseInt(parts[1], 10);
    const [secondsText, millisecondsText] = parts[2].split(".");
    return (
        hours * 3600 + minutes * 60 + Number.parseInt(secondsText, 10) + Number.parseInt(millisecondsText, 10) / 1000
    );
}

export function secondsToTime(seconds: number, useShortFormat = false): string {
    if (useShortFormat) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        const wholeSecs = Math.floor(secs);
        const ms = Math.floor((secs - wholeSecs) * 1000);
        return `${minutes.toString().padStart(2, "0")}:${wholeSecs.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`;
    }

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    const wholeSecs = Math.floor(secs);
    const ms = Math.floor((secs - wholeSecs) * 1000);
    return `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${wholeSecs.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`;
}
