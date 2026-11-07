<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type PlayerProps, usePlayerPlayback } from "@/composables/usePlayerPlayback";
import PlayerInfoPanel from "./PlayerInfoPanel.vue";
import PlayerControls from "./player/PlayerControls.vue";
import PlayerStatusOverlays from "./player/PlayerStatusOverlays.vue";

const props = defineProps<PlayerProps>();
defineEmits<{ close: [] }>();
const { t } = useI18n();
const videoElement = ref<HTMLVideoElement | null>(null);
const volume = ref(1);
const isMuted = ref(false);
const { togglePlay, canRetry, videoSrc, currentJobId, isPlaying, currentTime, duration, isLoading, loadingMessage, errorMessage, audioTracks, subtitleTracks, progressPercent, displayCurrentTime, bufferedPercentages, selectedResolutionLabel, playbackInfo, mediaInfo, codecInfo, transcodeReasons, selectedAudioTrack, selectedSubtitleTrack, selectedResolution, availableResolutions, isHlsPlayback, initializePlayback, applyInitialTrackSelection, selectAudioTrack, selectSubtitleTrack, selectResolution, seek, absolutePosition, onLoadedMetadata, onTimeUpdate, onProgress, onPlay, onPause, onError, onCanPlay, onWaiting, onPlaying } = usePlayerPlayback(props, videoElement, volume, isMuted, showControls);
const controlsVisible = ref(true);

const controlsTimeout = ref<ReturnType<typeof setTimeout> | null>(null);

const isFullscreen = ref(false);

const hoverTime = ref<number | null>(null);

const showAudioMenu = ref(false);

const showSubtitleMenu = ref(false);

const showResolutionMenu = ref(false);

const showInfoPanel = ref(false);

const hoverPercent = computed(() => {
  if (duration.value === 0 || hoverTime.value === null) return 0;
  return (hoverTime.value / duration.value) * 100;
});

onMounted(async () => {
  const savedVolume = localStorage.getItem("videoPlayerVolume");
  if (savedVolume !== null) {
    const parsed = Number.parseFloat(savedVolume);
    if (Number.isFinite(parsed)) volume.value = Math.max(0, Math.min(1, parsed));
  }

  // Load info panel visibility state
  const savedInfoPanelState = localStorage.getItem("playerInfoPanelVisible");
  if (savedInfoPanelState !== null) {
    showInfoPanel.value = savedInfoPanelState === "true";
  }

  // Initialize duration from media file metadata
  if (props.mediaFile?.duration) {
    duration.value = props.mediaFile.duration;
  }

  // Ensure controls are visible initially
  controlsVisible.value = true;

  // Add click outside handler to close menus
  document.addEventListener('click', closeAllMenus);

  setupFullscreenListeners();
  setupKeyboardShortcuts();

  // Initialize playback
  applyInitialTrackSelection();
  await initializePlayback();
});

onUnmounted(() => {
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  removeFullscreenListeners();
  window.removeEventListener("keydown", handleKeyDown);
  document.removeEventListener('click', closeAllMenus);
});

function closeAllMenus() {
  showAudioMenu.value = false;
  showSubtitleMenu.value = false;
  showResolutionMenu.value = false;
}

function showControls() {
  controlsVisible.value = true;
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  // Don't auto-hide controls during loading or when not playing
  if (!isLoading.value && isPlaying.value) {
    controlsTimeout.value = setTimeout(() => {
      if (!isPlaying.value || isLoading.value || showAudioMenu.value || showSubtitleMenu.value || showResolutionMenu.value) return;
      controlsVisible.value = false;
    }, 3000);
  }
}

function hideControls() {
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  // Don't hide controls during loading or if any menus are open
  if (isPlaying.value && !isLoading.value && !showAudioMenu.value && !showSubtitleMenu.value && !showResolutionMenu.value) {
    controlsVisible.value = false;
  }
}


function setVolume(e: Event) {
  const target = e.target as HTMLInputElement;
  volume.value = parseFloat(target.value);
  if (videoElement.value) {
    videoElement.value.volume = volume.value;
    videoElement.value.muted = false;
    isMuted.value = false;
  }
  localStorage.setItem("videoPlayerVolume", volume.value.toString());
}

function toggleMute() {
  if (!videoElement.value) return;
  isMuted.value = !isMuted.value;
  videoElement.value.muted = isMuted.value;
}

function toggleFullscreen() {
  const container = videoElement.value?.closest(".custom-video-player");
  if (!container) return;

  if (!document.fullscreenElement) {
    container.requestFullscreen().catch((err) => {
      console.error("Error attempting to enable fullscreen:", err);
    });
  } else {
    document.exitFullscreen();
  }
}

function setupFullscreenListeners() {
  document.addEventListener("fullscreenchange", handleFullscreenChange);
  document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
}

function removeFullscreenListeners() {
  document.removeEventListener("fullscreenchange", handleFullscreenChange);
  document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
}

function handleFullscreenChange() {
  isFullscreen.value = !!document.fullscreenElement;
}

function setupKeyboardShortcuts() {
  window.addEventListener("keydown", handleKeyDown);
}

function handleKeyDown(e: KeyboardEvent) {
  if (!videoElement.value) return;
  if (e.target instanceof Element && e.target.closest("button, input, select, textarea, [contenteditable=true]")) return;

  switch (e.key) {
    case " ":
      e.preventDefault();
      togglePlay();
      break;
    case "ArrowLeft":
      e.preventDefault();
      seek(absolutePosition() - 10);
      break;
    case "ArrowRight":
      e.preventDefault();
      seek(absolutePosition() + 10);
      break;
    case "ArrowUp":
      e.preventDefault();
      volume.value = Math.min(1, volume.value + 0.1);
      if (videoElement.value) videoElement.value.volume = volume.value;
      break;
    case "ArrowDown":
      e.preventDefault();
      volume.value = Math.max(0, volume.value - 0.1);
      if (videoElement.value) videoElement.value.volume = volume.value;
      break;
    case "m":
    case "M":
      e.preventDefault();
      toggleMute();
      break;
    case "f":
    case "F":
      e.preventDefault();
      toggleFullscreen();
      break;
  }
}

function onVolumeChange() {
  if (videoElement.value) {
    volume.value = videoElement.value.volume;
    isMuted.value = videoElement.value.muted;
  }
}

function toggleAudioMenu() {
  showSubtitleMenu.value = false;
  showResolutionMenu.value = false;
  showAudioMenu.value = !showAudioMenu.value;
}

function toggleSubtitleMenu() {
  showAudioMenu.value = false;
  showResolutionMenu.value = false;
  showSubtitleMenu.value = !showSubtitleMenu.value;
}

function toggleResolutionMenu() {
  showAudioMenu.value = false;
  showSubtitleMenu.value = false;
  showResolutionMenu.value = !showResolutionMenu.value;
}

function toggleInfoPanel() {
  showInfoPanel.value = !showInfoPanel.value;
  localStorage.setItem("playerInfoPanelVisible", showInfoPanel.value.toString());
}
</script>

<template>
  <section
    :aria-label="t('player.info.title')"
    class="custom-video-player relative w-full h-full flex items-center justify-center bg-black"
    @mousemove="showControls"
    @mouseleave="hideControls"
    @focusin="showControls"
  >
    <video
      ref="videoElement"
      :src="videoSrc || undefined"
      class="w-full h-full object-contain"
      playsinline
      preload="auto"
      crossorigin="anonymous"
      @loadedmetadata="onLoadedMetadata"
      @timeupdate="onTimeUpdate"
      @progress="onProgress"
      @play="onPlay"
      @pause="onPause"
      @volumechange="onVolumeChange"
      @error="onError"
      @canplay="onCanPlay"
      @waiting="onWaiting"
      @playing="onPlaying"
    />

    <PlayerStatusOverlays
      :can-retry="canRetry"
      :is-loading="isLoading"
      :loading-message="loadingMessage"
      :error-message="errorMessage"
      @retry="initializePlayback"
      @close="$emit('close')"
    />

    <PlayerControls
      :visible="controlsVisible && !errorMessage"
      :is-playing="isPlaying"
      :display-current-time="displayCurrentTime"
      :duration="duration"
      :volume="volume"
      :is-muted="isMuted"
      :is-fullscreen="isFullscreen"
      :progress-percent="progressPercent"
      :hover-time="hoverTime"
      :hover-percent="hoverPercent"
      :buffered-percentages="bufferedPercentages"
      :audio-tracks="audioTracks"
      :subtitle-tracks="subtitleTracks"
      :available-resolutions="availableResolutions"
      :selected-audio-track="selectedAudioTrack"
      :selected-subtitle-track="selectedSubtitleTrack"
      :selected-resolution="selectedResolution"
      :selected-resolution-label="selectedResolutionLabel"
      :show-audio-menu="showAudioMenu"
      :show-subtitle-menu="showSubtitleMenu"
      :show-resolution-menu="showResolutionMenu"
      @toggle-play="togglePlay"
      @seek="seek"
      @progress-hover="hoverTime = $event"
      @clear-hover="hoverTime = null"
      @set-volume="setVolume"
      @toggle-mute="toggleMute"
      @toggle-audio-menu="toggleAudioMenu"
      @select-audio-track="showAudioMenu = false; selectAudioTrack($event)"
      @toggle-subtitle-menu="toggleSubtitleMenu"
      @select-subtitle-track="showSubtitleMenu = false; selectSubtitleTrack($event)"
      @toggle-resolution-menu="toggleResolutionMenu"
      @select-resolution="showResolutionMenu = false; selectResolution($event)"
      @toggle-info-panel="toggleInfoPanel"
      @toggle-fullscreen="toggleFullscreen"
      @close="$emit('close')"
    />

    <!-- Player Info Panel -->
    <PlayerInfoPanel
      :is-visible="showInfoPanel"
      :playback-info="playbackInfo"
      :media-info="mediaInfo"
      :codec-info="codecInfo"
      :transcode-reasons="transcodeReasons"
      :current-job-id="currentJobId"
      @toggle="toggleInfoPanel"
    />
  </section>
</template>
