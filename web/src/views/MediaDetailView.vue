<script setup lang="ts">
import { computed, onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { type MediaFile, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";
import {
  type AudioTrackOption,
  getAudioTrackLabel,
  getSubtitleTrackLabel,
  type SubtitleTrackOption,
} from "@/services/playerUi";
import MenuBar from "../components/MenuBar.vue";

type VideoTrackOption = MediaFile["video_tracks"][number];

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const mediaFile: Ref<MediaFile | null> = ref(null);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");
const thumbnailFailed = ref(false);
const selectedVideoStreamIndex = ref<number | null>(null);
const selectedAudioStreamIndex = ref<number | null>(null);
const selectedSubtitleStreamIndex = ref<number | null>(null);

const audioTracks = computed(() => (mediaFile.value?.audio_tracks || []) as AudioTrackOption[]);
const videoTracks = computed(() => (mediaFile.value?.video_tracks || []) as VideoTrackOption[]);
const subtitleTracks = computed(() => (mediaFile.value?.subtitle_tracks || []) as SubtitleTrackOption[]);
const displayInfo = computed(() =>
  mediaFile.value?.file_name
    ? getMediaTitleInfo(mediaFile.value.file_name)
    : { title: mediaFile.value?.id ? String(mediaFile.value.id) : "", year: null },
);
const subtitleSelectValue = computed({
  get: () => selectedSubtitleStreamIndex.value ?? -1,
  set: (value: number) => {
    selectedSubtitleStreamIndex.value = value === -1 ? null : value;
  },
});

async function loadMedia(): Promise<void> {
  loading.value = true;
  error.value = "";

  try {
    mediaFile.value = await media.getMediaFile(Number(route.params.id));
    selectedVideoStreamIndex.value =
      videoTracks.value.find((track) => track.is_default)?.stream_index ??
      videoTracks.value[0]?.stream_index ??
      null;
    selectedAudioStreamIndex.value =
      audioTracks.value.find((track) => track.is_default)?.stream_index ??
      audioTracks.value[0]?.stream_index ??
      null;
  } catch (err: unknown) {
    console.error("Failed to load media:", err);
    error.value = t("mediaDetail.loadFailed");
  } finally {
    loading.value = false;
  }
}

function goBack(): void {
  router.push("/");
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return t("mediaDetail.duration.hoursMinutes", { hours, minutes });
  }
  return t("mediaDetail.duration.minutes", { minutes });
}

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

function handlePlayClick(): void {
  if (mediaFile.value?.id) {
    router.push({
      name: "player",
      params: { id: String(mediaFile.value.id) },
      query: {
        ...(selectedAudioStreamIndex.value !== null
          ? { audio: String(selectedAudioStreamIndex.value) }
          : {}),
        ...(selectedSubtitleStreamIndex.value !== null
          ? { subtitle: String(selectedSubtitleStreamIndex.value) }
          : {}),
      },
    });
  }
}

function getMediaTitle(): string {
  return displayInfo.value.title;
}

function thumbnailUrl(): string | null {
  if (!mediaFile.value?.id || thumbnailFailed.value) return null;
  return media.getThumbnailUrl(mediaFile.value.id);
}

onMounted(() => {
  loadMedia();
});
</script>

<template>
  <div class="media-detail-view min-h-screen bg-gray-900">
    <MenuBar />
    <div v-if="loading" class="container mx-auto px-6 py-8 text-center text-gray-400">
      {{ t("mediaDetail.loading") }}
    </div>

    <div v-else-if="error" class="container mx-auto px-6 py-8 text-center">
      <p class="text-red-400 mb-4">{{ error }}</p>
      <button
        @click="loadMedia"
        class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ t("common.retry") }}
      </button>
    </div>

    <div v-else-if="mediaFile" class="relative">
      <!-- Header -->
      <div class="relative h-64 md:h-96 overflow-hidden bg-gray-800">
        <img
          v-if="thumbnailUrl()"
          :src="thumbnailUrl() || undefined"
          :alt="getMediaTitle()"
          class="absolute inset-0 h-full w-full object-cover opacity-50 blur-sm scale-105"
          @error="thumbnailFailed = true"
        />
        <div
          class="absolute inset-0 bg-linear-to-b from-transparent via-gray-900/50 to-gray-900"
        ></div>

        <!-- Back Button -->
        <button
          @click="goBack"
          class="absolute top-4 left-4 z-20 bg-black/50 hover:bg-black/70 backdrop-blur-xs text-white p-2 rounded-full transition-all duration-200 flex items-center justify-center"
          :aria-label="t('mediaDetail.back')"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 19l-7-7 7-7"
            />
          </svg>
        </button>
      </div>

      <!-- Content -->
      <div class="container mx-auto px-6 pt-0 pb-8 -mt-56 relative z-10">
        <div class="flex flex-col md:flex-row gap-8">
          <!-- Poster Placeholder -->
          <div class="shrink-0">
            <div
              class="w-48 md:w-64 aspect-2/3 bg-gray-800 rounded-lg shadow-2xl overflow-hidden flex items-center justify-center"
            >
              <img
                v-if="thumbnailUrl()"
                :src="thumbnailUrl() || undefined"
                :alt="getMediaTitle()"
                class="h-full w-full object-cover"
                @error="thumbnailFailed = true"
              />
              <svg
                v-else
                class="w-24 h-24 text-gray-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
            </div>
          </div>

          <!-- Info -->
          <div class="flex-1 text-white">
            <div class="mb-4 flex items-start justify-between gap-6">
              <h1 class="min-w-0 text-4xl md:text-5xl font-bold">{{ getMediaTitle() }}</h1>
              <button
                v-if="mediaFile.id"
                @click="handlePlayClick"
                class="shrink-0 bg-primary-600 hover:bg-primary-700 text-white font-semibold py-2.5 px-6 rounded-lg transition-colors duration-200 flex items-center gap-2"
              >
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"
                  />
                </svg>
                {{ t("mediaDetail.play") }}
              </button>
            </div>
            <div class="flex items-center gap-4 mb-6 text-gray-300">
              <span v-if="mediaFile.duration">{{ formatDuration(mediaFile.duration) }}</span>
              <span v-if="mediaFile.duration && displayInfo.year">•</span>
              <span v-if="displayInfo.year">{{ displayInfo.year }}</span>
            </div>

            <div class="max-w-2xl space-y-2 text-sm">
              <label class="flex items-center gap-3">
                <span class="w-24 shrink-0 text-gray-400">{{ t("mediaDetail.tracks.video") }}</span>
                <select
                  v-model.number="selectedVideoStreamIndex"
                  class="media-track-select"
                  :disabled="videoTracks.length <= 1"
                >
                  <option
                    v-for="track in videoTracks"
                    :key="track.id"
                    :value="track.stream_index"
                  >
                    {{ formatVideoTrackLabel(track) }}
                  </option>
                </select>
              </label>
              <label class="flex items-center gap-3">
                <span class="w-24 shrink-0 text-gray-400">{{ t("mediaDetail.tracks.audio") }}</span>
                <select
                  v-model.number="selectedAudioStreamIndex"
                  class="media-track-select"
                  :disabled="audioTracks.length <= 1"
                >
                  <option
                    v-for="track in audioTracks"
                    :key="track.id"
                    :value="track.stream_index"
                  >
                    {{ formatAudioTrackLabel(track) }}
                  </option>
                </select>
              </label>
              <label class="flex items-center gap-3">
                <span class="w-24 shrink-0 text-gray-400">{{
                  t("mediaDetail.tracks.subtitles")
                }}</span>
                <select
                  v-model.number="subtitleSelectValue"
                  class="media-track-select"
                  :disabled="subtitleTracks.length <= 1"
                >
                  <option :value="-1">{{ t("mediaDetail.track.subtitlesOff") }}</option>
                  <option
                    v-for="track in subtitleTracks"
                    :key="track.id"
                    :value="track.stream_index"
                  >
                    {{ getSubtitleTrackLabel(track) }}
                  </option>
                </select>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="container mx-auto px-6 py-8 text-center text-white">
      <p class="text-xl">{{ t("mediaDetail.notFound") }}</p>
      <router-link to="/" class="text-primary-400 hover:text-primary-300 mt-4 inline-block">
        {{ t("mediaDetail.backHome") }}
      </router-link>
    </div>
  </div>
</template>

<style scoped>
.media-track-select {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  field-sizing: content;
  appearance: none;
  border: 1px solid transparent;
  border-radius: 0.375rem;
  background-color: transparent;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 20 20' fill='none' stroke='%239ca3af' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 8 4 4 4-4'/%3E%3C/svg%3E");
  background-position: right 0.2rem center;
  background-repeat: no-repeat;
  color: rgb(209 213 219);
  padding: 0.125rem 1.25rem 0.125rem 0.35rem;
  outline: none;
  transition:
    border-color 160ms ease,
    color 160ms ease;
}

.media-track-select:hover:not(:disabled),
.media-track-select:focus {
  border-color: rgba(59, 130, 246, 0.55);
  color: white;
}

.media-track-select:disabled {
  cursor: default;
  opacity: 1;
  background-image: none;
  color: rgb(209 213 219);
  padding-right: 0.35rem;
}

.media-track-select option {
  background-color: rgb(17 24 39);
  color: rgb(229 231 235);
}
</style>
