<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { getAccessToken } from "@/api/client";

const props = defineProps({
  movieId: {
    type: [String, Number],
    required: true,
  },
});

const emit = defineEmits(["format-error"]);

const videoElement = ref(null);
const videoSrc = ref("");

// Build streaming URL with authentication token
function getStreamUrl() {
  if (!props.movieId) return "";
  const token = getAccessToken();
  const baseUrl = `/api/v1/stream/${props.movieId}`;
  return token ? `${baseUrl}?api_key=${token}` : baseUrl;
}

function onError() {
  const video = videoElement.value;
  const error = video?.error;

  // Check if it's a format error (code 4 = MEDIA_ERR_SRC_NOT_SUPPORTED)
  if (error?.code === 4 || error?.message?.includes("DEMUXER_ERROR")) {
    // Detect the content type to show helpful error message
    if (video?.src) {
      fetch(video.src, { method: "GET", headers: { Range: "bytes=0-1023" } })
        .then((response) => {
          const contentType = response.headers.get("content-type");
          emit("format-error", { contentType, errorMessage: error?.message });
        })
        .catch(() => {
          // If fetch fails, still emit with available info
          emit("format-error", { contentType: null, errorMessage: error?.message });
        });
    }
  }
}

function setupVideo() {
  if (!props.movieId) return;

  const url = getStreamUrl();
  videoSrc.value = url;

  // Also ensure the video element gets it if it exists
  if (videoElement.value) {
    videoElement.value.src = url;
    requestAnimationFrame(() => {
      videoElement.value.load();
    });
  }
}

// Watch for changes in movieId and update the video source
watch(
  () => props.movieId,
  async (newId) => {
    if (newId) {
      await nextTick();
      setupVideo();
    }
  },
  { immediate: true },
);

// Watch for when video element becomes available
watch(videoElement, (element) => {
  if (element && props.movieId && videoSrc.value) {
    element.src = videoSrc.value;
    element.load();
  }
});

onMounted(async () => {
  await nextTick();
  if (props.movieId) {
    setupVideo();
  }
});
</script>

<template>
  <div class="video-player w-full">
    <video
      ref="videoElement"
      :src="videoSrc"
      class="w-full h-auto max-h-[80vh]"
      controls
      playsinline
      preload="auto"
      @error="onError"
    ></video>
  </div>
</template>
