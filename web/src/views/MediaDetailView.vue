<script setup lang="ts">
import { onMounted, type Ref, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { type MediaFile, media } from "@/api/client";
import MenuBar from "../components/MenuBar.vue";

const route = useRoute();
const router = useRouter();
const mediaFile: Ref<MediaFile | null> = ref(null);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");

async function loadMedia(): Promise<void> {
  loading.value = true;
  error.value = "";

  try {
    // Load MediaFile first
    mediaFile.value = await media.getMediaFile(Number(route.params.id));
  } catch (err: unknown) {
    console.error("Failed to load media:", err);
    error.value = "Failed to load media details. Please try again.";
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
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

function formatDurationSeconds(seconds: number): string {
  return formatDuration(seconds);
}

function formatBitrate(bitrate: number): string {
  if (bitrate >= 1000000) {
    return `${(bitrate / 1000000).toFixed(2)} Mbps`;
  }
  return `${(bitrate / 1000).toFixed(0)} Kbps`;
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1073741824) {
    return `${(bytes / 1073741824).toFixed(2)} GB`;
  }
  if (bytes >= 1048576) {
    return `${(bytes / 1048576).toFixed(2)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(2)} KB`;
  }
  return `${bytes} B`;
}

function handlePlayClick(): void {
  if (mediaFile.value?.id) {
    router.push({ name: "player", params: { id: String(mediaFile.value.id) } });
  }
}

function getMediaTitle(): string {
  if (!mediaFile.value?.file_name) return mediaFile.value?.id ? String(mediaFile.value.id) : "";
  // Extract title from file_name by removing extension
  const name = mediaFile.value.file_name;
  const lastDot = name.lastIndexOf(".");
  return lastDot > 0 ? name.substring(0, lastDot) : name;
}

onMounted(() => {
  loadMedia();
});
</script>

<template>
  <div class="media-detail-view min-h-screen bg-gray-900">
    <MenuBar />
    <div v-if="loading" class="container mx-auto px-6 py-8 text-center text-gray-400">
      Loading media...
    </div>

    <div v-else-if="error" class="container mx-auto px-6 py-8 text-center">
      <p class="text-red-400 mb-4">{{ error }}</p>
      <button
        @click="loadMedia"
        class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        Retry
      </button>
    </div>

    <div v-else-if="mediaFile" class="relative">
      <!-- Header -->
      <div class="relative h-64 md:h-96 overflow-hidden bg-gray-800">
        <div
          class="absolute inset-0 bg-linear-to-b from-transparent via-gray-900/50 to-gray-900"
        ></div>

        <!-- Back Button -->
        <button
          @click="goBack"
          class="absolute top-4 left-4 z-20 bg-black/50 hover:bg-black/70 backdrop-blur-xs text-white p-2 rounded-full transition-all duration-200 flex items-center justify-center"
          aria-label="Go back"
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
      <div class="container mx-auto px-6 py-8 -mt-32 relative z-10">
        <div class="flex flex-col md:flex-row gap-8">
          <!-- Poster Placeholder -->
          <div class="shrink-0">
            <div
              class="w-48 md:w-64 aspect-2/3 bg-gray-800 rounded-lg shadow-2xl flex items-center justify-center"
            >
              <svg
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
            <h1 class="text-4xl md:text-5xl font-bold mb-4">{{ getMediaTitle() }}</h1>
            <div class="flex items-center gap-4 mb-4 text-gray-300">
              <span v-if="mediaFile.duration">{{ formatDuration(mediaFile.duration) }}</span>
              <span v-if="mediaFile.duration && mediaFile.file_extension">•</span>
              <span v-if="mediaFile.file_extension">{{
                mediaFile.file_extension.toUpperCase()
              }}</span>
            </div>

            <!-- MediaFile Information -->
            <div class="mb-6 p-4 bg-gray-800/50 rounded-lg">
              <h2 class="text-xl font-semibold mb-3">File Information</h2>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                <div>
                  <span class="text-gray-400">File:</span>
                  <span class="ml-2 text-gray-300">{{ mediaFile.file_name }}</span>
                </div>
                <div>
                  <span class="text-gray-400">Path:</span>
                  <span class="ml-2 text-gray-300 break-all">{{ mediaFile.file_path }}</span>
                </div>
                <div v-if="mediaFile.duration">
                  <span class="text-gray-400">Duration:</span>
                  <span class="ml-2 text-gray-300">{{
                    formatDurationSeconds(mediaFile.duration)
                  }}</span>
                </div>
                <div v-if="mediaFile.width && mediaFile.height">
                  <span class="text-gray-400">Resolution:</span>
                  <span class="ml-2 text-gray-300"
                    >{{ mediaFile.width }}x{{ mediaFile.height }}</span
                  >
                </div>
                <div v-if="mediaFile.codec">
                  <span class="text-gray-400">Codec:</span>
                  <span class="ml-2 text-gray-300">{{ mediaFile.codec }}</span>
                </div>
                <div v-if="mediaFile.bitrate">
                  <span class="text-gray-400">Bitrate:</span>
                  <span class="ml-2 text-gray-300">{{ formatBitrate(mediaFile.bitrate) }}</span>
                </div>
                <div>
                  <span class="text-gray-400">Size:</span>
                  <span class="ml-2 text-gray-300">{{
                    formatFileSize(mediaFile.file_size || 0)
                  }}</span>
                </div>
              </div>
            </div>

            <button
              v-if="mediaFile.id"
              @click="handlePlayClick"
              class="bg-primary-600 hover:bg-primary-700 text-white font-semibold py-3 px-8 rounded-lg transition-colors duration-200 flex items-center gap-2"
            >
              <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                <path
                  d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"
                />
              </svg>
              Play
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="container mx-auto px-6 py-8 text-center text-white">
      <p class="text-xl">Media not found</p>
      <router-link to="/" class="text-primary-400 hover:text-primary-300 mt-4 inline-block">
        Back to home
      </router-link>
    </div>
  </div>
</template>
