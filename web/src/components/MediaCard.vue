<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { type MediaFile, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";

const props = defineProps<{
  mediaFile: MediaFile;
}>();

const router = useRouter();
const thumbnailFailed = ref(false);

const displayInfo = computed(() => {
  return getMediaTitleInfo(props.mediaFile.file_name);
});

function handleClick(): void {
  router.push({ name: "media-detail", params: { id: String(props.mediaFile.id) } });
}

function getMediaTitle(): string {
  return displayInfo.value.title;
}

function thumbnailUrl(): string | null {
  if (!props.mediaFile.id || thumbnailFailed.value) return null;
  return media.getThumbnailUrl(props.mediaFile.id);
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

</script>

<template>
  <div
    class="media-card aspect-2/3 cursor-pointer hover:z-10 focus:z-10 focus:outline-hidden"
    role="button"
    tabindex="0"
    :aria-label="getMediaTitle()"
    @click="handleClick"
    @keydown.enter.prevent="handleClick"
    @keydown.space.prevent="handleClick"
  >
    <div class="relative w-full h-full overflow-hidden rounded-lg bg-gray-800 shadow-lg">
      <img
        v-if="thumbnailUrl()"
        :src="thumbnailUrl() || undefined"
        :alt="getMediaTitle()"
        class="absolute inset-0 w-full h-full object-cover"
        loading="lazy"
        @error="thumbnailFailed = true"
      />
      <div
        v-else
        class="absolute inset-0 flex items-center justify-center bg-linear-to-br from-gray-700 to-gray-900"
      >
        <svg class="w-16 h-16 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
          />
        </svg>
      </div>
      <div
        class="absolute inset-0 bg-linear-to-t from-black/85 via-black/20 to-transparent"
      >
        <div class="absolute bottom-0 left-0 right-0 p-4">
          <h3 class="media-card__title text-white font-bold text-lg mb-1">
            {{ getMediaTitle() }}
          </h3>
          <div class="flex items-center justify-between gap-3 mt-2 text-xs text-gray-400">
            <span v-if="mediaFile.duration">{{ formatDuration(mediaFile.duration) }}</span>
            <span v-else></span>
            <span v-if="displayInfo.year">{{ displayInfo.year }}</span>
          </div>
        </div>
      </div>
      <div
        class="media-card__selection-glow pointer-events-none absolute inset-0 rounded-lg"
      ></div>
      <div
        class="media-card__selection-ring pointer-events-none absolute inset-0 rounded-lg"
      ></div>
    </div>
  </div>
</template>

<style scoped>
.media-card__title {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.media-card__selection-glow,
.media-card__selection-ring {
  opacity: 0;
  transition:
    opacity 520ms cubic-bezier(0.16, 1, 0.3, 1),
    filter 520ms cubic-bezier(0.16, 1, 0.3, 1);
}

.media-card__selection-glow {
  filter: blur(12px);
  box-shadow: inset 0 0 24px rgba(59, 130, 246, 0.44);
}

.media-card__selection-ring {
  box-shadow:
    inset 0 0 0 2px rgba(59, 130, 246, 0.78),
    inset 0 0 10px rgba(59, 130, 246, 0.18);
  filter: blur(0.35px);
}

.media-card:hover .media-card__selection-glow,
.media-card:focus .media-card__selection-glow {
  opacity: 0.75;
  filter: blur(7px);
}

.media-card:hover .media-card__selection-ring,
.media-card:focus .media-card__selection-ring {
  opacity: 1;
  filter: blur(0);
}
</style>
