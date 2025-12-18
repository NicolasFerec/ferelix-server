<script setup lang="ts">
import { onMounted, onUnmounted, type Ref, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { type MediaFile, media } from "@/api/client";
import CustomVideoPlayer from "../components/CustomVideoPlayer.vue";

const route = useRoute();
const router = useRouter();
const mediaFile: Ref<MediaFile | null> = ref(null);
const loading: Ref<boolean> = ref(false);
const error: Ref<string | null> = ref(null);

async function loadMedia(): Promise<void> {
  loading.value = true;
  error.value = null;

  try {
    mediaFile.value = await media.getMediaFile(Number(route.params.id));
  } catch (err: unknown) {
    console.error("Failed to load media:", err);
    error.value = err instanceof Error ? err.message : "Failed to load media";
  } finally {
    loading.value = false;
  }
}

function handleClose(): void {
  router.back();
}

function handleEscape(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    handleClose();
  }
}

onMounted(() => {
  loadMedia();
  window.addEventListener("keydown", handleEscape);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleEscape);
});
</script>

<template>
  <div class="player-view fixed inset-0 bg-black z-50">
    <CustomVideoPlayer v-if="mediaFile" :media-file="mediaFile" @close="handleClose" />
    <div v-else-if="loading" class="flex items-center justify-center h-full text-white">
      <p>{{ $t('player.loading') }}</p>
    </div>
    <div v-else-if="error" class="flex flex-col items-center justify-center h-full text-white">
      <p class="mb-4">{{ $t('player.error') }}</p>
      <button @click="loadMedia" class="px-4 py-2 bg-primary-600 hover:bg-primary-700 rounded-md">
        {{ $t('player.retry') }}
      </button>
    </div>
  </div>
</template>
