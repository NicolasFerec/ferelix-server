<script lang="ts">
export type TrackSelection = Partial<Record<"video" | "audio" | "subtitle", number>>;
</script>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { MediaFile } from "@/api/client";
import {
  type AudioTrackOption,
  getAudioTrackLabel,
  getSubtitleTrackLabel,
  type SubtitleTrackOption,
} from "@/services/playerUi";
import DropdownSelect, { type DropdownOption } from "./DropdownSelect.vue";

const props = defineProps<{ file: MediaFile }>();
const selection = defineModel<TrackSelection>({ required: true });
const { t } = useI18n();
type VideoTrackOption = MediaFile["video_tracks"][number];
const videoTracks = computed(() => props.file.video_tracks ?? []);
const audioTracks = computed(() => (props.file.audio_tracks ?? []) as AudioTrackOption[]);
const subtitleTracks = computed(() => (props.file.subtitle_tracks ?? []) as SubtitleTrackOption[]);

const defaults = computed(() => ({
  video: props.file.default_video_stream_index ?? null,
  audio: props.file.default_audio_stream_index ?? null,
  subtitle: props.file.default_subtitle_stream_index ?? -1,
}));

function selectTrack(kind: keyof TrackSelection, value: string | number | null) {
  const next = { ...selection.value };
  if (typeof value === "number" && value !== defaults.value[kind]) next[kind] = value;
  else delete next[kind];
  selection.value = next;
}

const videoTrackOptions = computed<DropdownOption[]>(() => [
  ...(!videoTracks.value.length ? [{ value: null, label: t("mediaDetail.track.unknown") }] : []),
  ...videoTracks.value.map((track) => ({
    value: track.stream_index,
    label: formatVideoTrackLabel(track) || t("mediaDetail.track.unknown"),
  })),
]);
const audioTrackOptions = computed<DropdownOption[]>(() => [
  ...(!audioTracks.value.length ? [{ value: null, label: t("mediaDetail.track.unknown") }] : []),
  ...audioTracks.value.map((track) => ({
    value: track.stream_index,
    label: formatAudioTrackLabel(track),
  })),
]);
const subtitleTrackOptions = computed<DropdownOption[]>(() => [
  { value: -1, label: t("mediaDetail.track.subtitlesOff") },
  ...subtitleTracks.value.map((track) => ({
    value: track.stream_index,
    label: getSubtitleTrackLabel(track),
  })),
]);
function formatBitrate(bitrate: number): string {
  if (bitrate >= 1000000) {
    return `${(bitrate / 1000000).toFixed(2)} Mbps`;
  }
  return `${(bitrate / 1000).toFixed(0)} Kbps`;
}

function formatTrackBitrate(bitrate?: number | null): string {
  return bitrate ? formatBitrate(bitrate) : t("mediaDetail.track.unknown");
}

function formatSampleRate(sampleRate?: number | null): string {
  if (!sampleRate) return t("mediaDetail.track.unknown");
  return `${(sampleRate / 1000).toFixed(sampleRate % 1000 === 0 ? 0 : 1)} kHz`;
}

function formatVideoTrackLabel(track: VideoTrackOption): string {
  return [
    track.width && track.height ? `${track.width}x${track.height}` : null,
    track.codec?.toUpperCase(),
    getVideoRangeLabel(track),
  ]
    .filter(Boolean)
    .join(" · ");
}

function formatAudioTrackLabel(track: AudioTrackOption): string {
  return [
    getAudioTrackLabel(track),
    track.codec?.toUpperCase(),
    track.bitrate ? formatTrackBitrate(track.bitrate) : null,
    track.sample_rate ? formatSampleRate(track.sample_rate) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function getVideoRangeLabel(track: VideoTrackOption): string | null {
  const metadata = [
    track.profile,
    track.color_space,
    track.color_primaries,
    track.color_transfer,
    track.pixel_format,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (metadata.includes("dolby") || metadata.includes("dvhe") || metadata.includes("dovi")) {
    return "DV";
  }
  if (
    metadata.includes("bt2020") ||
    metadata.includes("smpte2084") ||
    metadata.includes("arib-std-b67") ||
    metadata.includes("hlg")
  ) {
    return "HDR";
  }
  if (track.bit_depth && track.bit_depth > 8) {
    return `${track.bit_depth}-bit`;
  }

  return null;
}

</script>

<template>
  <div class="max-w-2xl space-y-2 text-sm">
    <label for="video-stream" class="flex items-center gap-3">
      <span class="w-24 shrink-0 text-gray-400">{{ t("mediaDetail.tracks.video") }}</span>
      <DropdownSelect
        id="video-stream"
        :model-value="selection.video ?? defaults.video"
        @update:model-value="selectTrack('video', $event)"
        :options="videoTrackOptions"
        :disabled="videoTracks.length <= 1"
      />
    </label>
    <label for="audio-stream" class="flex items-center gap-3">
      <span class="w-24 shrink-0 text-gray-400">{{ t("mediaDetail.tracks.audio") }}</span>
      <DropdownSelect
        id="audio-stream"
        :model-value="selection.audio ?? defaults.audio"
        @update:model-value="selectTrack('audio', $event)"
        :options="audioTrackOptions"
        :disabled="audioTrackOptions.length <= 1"
      />
    </label>
    <label for="subtitle-stream" class="flex items-center gap-3">
      <span class="w-24 shrink-0 text-gray-400">{{
        t("mediaDetail.tracks.subtitles")
      }}</span>
      <DropdownSelect
        id="subtitle-stream"
        :model-value="selection.subtitle ?? defaults.subtitle"
        @update:model-value="selectTrack('subtitle', $event)"
        :options="subtitleTrackOptions"
        :disabled="subtitleTrackOptions.length <= 1"
      />
    </label>
  </div>
</template>
