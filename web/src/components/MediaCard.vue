<script setup lang="ts">
import { useRouter } from "vue-router";
import { type MediaFile } from "@/api/client";

const props = defineProps<{
  mediaFile: MediaFile;
}>();

const router = useRouter();

function handleClick(): void {
  router.push({ name: "media-detail", params: { id: String(props.mediaFile.id) } });
}

function getMediaTitle(): string {
  if (!props.mediaFile) return "";
  // Extract title from file_name by removing extension
  const name = props.mediaFile.file_name;
  const lastDot = name.lastIndexOf(".");
  return lastDot > 0 ? name.substring(0, lastDot) : name;
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
  <div class="media-card aspect-2/3 cursor-pointer hover:z-10" @click="handleClick">
    <div class="relative w-full h-full overflow-hidden rounded-lg bg-gray-800 shadow-lg">
      <div
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
        class="absolute inset-0 bg-linear-to-t from-black/80 via-black/0 to-transparent opacity-0 hover:opacity-100 transition-opacity duration-300"
      >
        <div class="absolute bottom-0 left-0 right-0 p-4">
          <h3 class="text-white font-bold text-lg mb-1">{{ getMediaTitle() }}</h3>
          <div class="flex items-center gap-2 mt-2 text-xs text-gray-400">
            <span v-if="mediaFile.duration">{{ formatDuration(mediaFile.duration) }}</span>
            <span v-if="mediaFile.duration && mediaFile.file_extension">•</span>
            <span v-if="mediaFile.file_extension">{{
              mediaFile.file_extension.toUpperCase()
            }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
