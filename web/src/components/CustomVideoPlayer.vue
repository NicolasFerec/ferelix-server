<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { getAccessToken } from "@/api/client";

const props = defineProps({
  mediaFile: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(["close"]);

const { t } = useI18n();

const videoElement = ref(null);
const progressBar = ref(null);
const videoSrc = ref("");
const controlsVisible = ref(true);
const controlsTimeout = ref(null);
const isPlaying = ref(false);
const currentTime = ref(0);
const duration = ref(0);
const volume = ref(1);
const isMuted = ref(false);
const isFullscreen = ref(false);
const hoverTime = ref(null);
const showAudioMenu = ref(false);
const showSubtitleMenu = ref(false);
const selectedAudioTrack = ref(null);
const selectedSubtitleTrack = ref(null);

const audioTracks = computed(() => {
  return props.mediaFile?.audio_tracks || [];
});

const subtitleTracks = computed(() => {
  return props.mediaFile?.subtitle_tracks || [];
});

const progressPercent = computed(() => {
  if (duration.value === 0) return 0;
  return (currentTime.value / duration.value) * 100;
});

const hoverPercent = computed(() => {
  if (!progressBar.value || hoverTime.value === null) return 0;
  return (hoverTime.value / duration.value) * 100;
});

// Load volume from localStorage
onMounted(() => {
  const savedVolume = localStorage.getItem("videoPlayerVolume");
  if (savedVolume !== null) {
    volume.value = parseFloat(savedVolume);
  }
  setupVideo();
  setupFullscreenListeners();
  setupKeyboardShortcuts();
});

onUnmounted(() => {
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  removeFullscreenListeners();
});

function setupVideo() {
  if (!props.mediaFile?.id) return;

  const token = getAccessToken();
  const baseUrl = `/api/v1/stream/${props.mediaFile.id}`;
  videoSrc.value = token ? `${baseUrl}?api_key=${token}` : baseUrl;

  nextTick(() => {
    if (videoElement.value) {
      // Ensure audio is enabled and not muted
      videoElement.value.muted = false;
      isMuted.value = false;
      videoElement.value.volume = volume.value > 0 ? volume.value : 1;
      if (volume.value === 0) {
        volume.value = 1;
      }
      videoElement.value.load();
    }
  });
}

function showControls() {
  controlsVisible.value = true;
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  controlsTimeout.value = setTimeout(() => {
    if (!isPlaying.value) return;
    controlsVisible.value = false;
  }, 3000);
}

function hideControls() {
  if (controlsTimeout.value) {
    clearTimeout(controlsTimeout.value);
  }
  if (isPlaying.value) {
    controlsVisible.value = false;
  }
}

function togglePlay() {
  if (!videoElement.value) return;
  if (isPlaying.value) {
    videoElement.value.pause();
  } else {
    videoElement.value.play();
  }
}

function seek(e) {
  if (!videoElement.value || !progressBar.value) return;
  const rect = progressBar.value.getBoundingClientRect();
  const percent = (e.clientX - rect.left) / rect.width;
  videoElement.value.currentTime = percent * duration.value;
}

function onProgressHover(e) {
  if (!progressBar.value || duration.value === 0) return;
  const rect = progressBar.value.getBoundingClientRect();
  const percent = (e.clientX - rect.left) / rect.width;
  hoverTime.value = percent * duration.value;
}

function setVolume(e) {
  volume.value = parseFloat(e.target.value);
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
  if (!videoElement.value) return;
  if (!document.fullscreenElement) {
    videoElement.value.requestFullscreen().catch((err) => {
      console.error("Error attempting to enable fullscreen:", err);
    });
  } else {
    document.exitFullscreen();
  }
}

function setupFullscreenListeners() {
  document.addEventListener("fullscreenchange", handleFullscreenChange);
  document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
  document.addEventListener("mozfullscreenchange", handleFullscreenChange);
  document.addEventListener("MSFullscreenChange", handleFullscreenChange);
}

function removeFullscreenListeners() {
  document.removeEventListener("fullscreenchange", handleFullscreenChange);
  document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
  document.removeEventListener("mozfullscreenchange", handleFullscreenChange);
  document.removeEventListener("MSFullscreenChange", handleFullscreenChange);
}

function handleFullscreenChange() {
  isFullscreen.value = !!(
    document.fullscreenElement ||
    document.webkitFullscreenElement ||
    document.mozFullScreenElement ||
    document.msFullscreenElement
  );
}

function setupKeyboardShortcuts() {
  window.addEventListener("keydown", handleKeyDown);
}

function handleKeyDown(e) {
  if (!videoElement.value) return;

  switch (e.key) {
    case " ":
      e.preventDefault();
      togglePlay();
      break;
    case "ArrowLeft":
      e.preventDefault();
      videoElement.value.currentTime = Math.max(0, videoElement.value.currentTime - 10);
      break;
    case "ArrowRight":
      e.preventDefault();
      videoElement.value.currentTime = Math.min(
        duration.value,
        videoElement.value.currentTime + 10,
      );
      break;
    case "ArrowUp":
      e.preventDefault();
      volume.value = Math.min(1, volume.value + 0.1);
      setVolume({ target: { value: volume.value } });
      break;
    case "ArrowDown":
      e.preventDefault();
      volume.value = Math.max(0, volume.value - 0.1);
      setVolume({ target: { value: volume.value } });
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

function onLoadedMetadata() {
  if (videoElement.value) {
    duration.value = videoElement.value.duration;

    // Ensure audio is not muted and volume is set
    videoElement.value.muted = false;
    isMuted.value = false;
    if (volume.value === 0) {
      volume.value = 1;
      videoElement.value.volume = 1;
    }

    // Setup audio tracks
    setupAudioTracks();

    // Setup subtitle tracks
    setupSubtitleTracks();
  }
}

function onTimeUpdate() {
  if (videoElement.value) {
    currentTime.value = videoElement.value.currentTime;
  }
}

function onPlay() {
  isPlaying.value = true;
}

function onPlaying() {
  // When video starts playing, check if audio is working
  if (videoElement.value) {
    // Small delay to let audio start
    setTimeout(() => {
      detectAudioPlayback();
    }, 500);
  }
}

function onPause() {
  isPlaying.value = false;
  controlsVisible.value = true;
}

function onVolumeChange() {
  if (videoElement.value) {
    volume.value = videoElement.value.volume;
    isMuted.value = videoElement.value.muted;
  }
}

function onError(e) {
  console.error("Video error:", e);
  if (videoElement.value?.error) {
    const error = videoElement.value.error;
    console.error("Video error code:", error.code);
    console.error("Video error message:", error.message);

    // Check if it's a codec/format issue
    if (error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      console.error("Video format not supported by browser");
    }
  }
}

function onLoadedData() {
  // Additional setup after video data is loaded
  if (videoElement.value) {
    // Ensure audio is still enabled
    if (videoElement.value.muted) {
      videoElement.value.muted = false;
      isMuted.value = false;
    }
    if (videoElement.value.volume === 0) {
      videoElement.value.volume = 1;
      volume.value = 1;
    }

    // Try to setup audio tracks again in case audioTracks weren't ready before
    setupAudioTracks();

    // Try to setup subtitles again in case textTracks weren't ready before
    setupSubtitleTracks();

    // Check if browser supports the video format
    checkFormatSupport();
  }
}

function checkFormatSupport() {
  if (!videoElement.value) return;

  const fileExtension = props.mediaFile?.file_extension?.toLowerCase();

  // Check if browser supports MKV/Matroska format
  if (fileExtension === ".mkv" || fileExtension === ".mka") {
    const mkvSupport = videoElement.value.canPlayType("video/x-matroska");
    if (!mkvSupport || mkvSupport === "") {
      // Try to detect if audio is actually playing after a delay
      setTimeout(() => {
        detectAudioPlayback();
      }, 2000);
    }
  }
}

function detectAudioPlayback() {
  if (!videoElement.value || videoElement.value.paused) return;

  try {
    // Try to use Web Audio API to detect if audio is playing
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaElementSource(videoElement.value);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    analyser.connect(audioContext.destination);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);

    // Clean up
    source.disconnect();
    analyser.disconnect();
    audioContext.close();
  } catch (e) {
    // Silent fail - detection is optional
  }
}

function formatTime(seconds) {
  if (!seconds || Number.isNaN(seconds)) return "0:00";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function getAudioTrackLabel(track) {
  const parts = [];
  if (track.language) {
    parts.push(track.language.toUpperCase());
  }
  if (track.channels) {
    if (track.channels === 2) {
      parts.push("Stereo");
    } else if (track.channels === 6) {
      parts.push("5.1");
    } else {
      parts.push(`${track.channels}ch`);
    }
  }
  if (track.title) {
    parts.push(track.title);
  }
  return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
}

function getSubtitleTrackLabel(track) {
  const parts = [];
  if (track.language) {
    parts.push(track.language.toUpperCase());
  }
  if (track.is_forced) {
    parts.push("(Forced)");
  }
  if (track.title) {
    parts.push(track.title);
  }
  return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
}

function selectAudioTrack(track) {
  selectedAudioTrack.value = track;
  showAudioMenu.value = false;

  if (!videoElement.value) return;

  // Ensure audio is enabled
  videoElement.value.muted = false;
  isMuted.value = false;
  if (videoElement.value.volume === 0) {
    videoElement.value.volume = 1;
    volume.value = 1;
  }

  // Use HTML5 audioTracks API to select the track
  const audioTracks = videoElement.value.audioTracks;

  if (audioTracks && audioTracks.length > 0) {
    // Disable all tracks first
    for (let i = 0; i < audioTracks.length; i++) {
      audioTracks[i].enabled = false;
    }

    // Try to find matching track by language or index
    let matchedTrack = null;

    // First try to match by language
    if (track.language) {
      for (let i = 0; i < audioTracks.length; i++) {
        const audioTrack = audioTracks[i];
        if (
          audioTrack.language === track.language.toLowerCase() ||
          audioTrack.language === track.language ||
          audioTrack.language === track.language.split("-")[0]
        ) {
          matchedTrack = audioTrack;
          break;
        }
      }
    }

    // If no language match, try to match by index (audio tracks are usually in order)
    if (!matchedTrack && audioTracks.value.length === audioTracks.length) {
      const trackIndex = audioTracks.value.findIndex((t) => t.id === track.id);
      if (trackIndex >= 0 && trackIndex < audioTracks.length) {
        matchedTrack = audioTracks[trackIndex];
      }
    }

    // If still no match, try to match by stream_index or position
    if (!matchedTrack) {
      const apiTracks = audioTracks.value;
      for (let i = 0; i < audioTracks.length && i < apiTracks.length; i++) {
        // Try to match by position/index
        if (apiTracks[i].id === track.id) {
          matchedTrack = audioTracks[i];
          break;
        }
      }
    }

    // If still no match, try the first available track as fallback
    if (!matchedTrack && audioTracks.length > 0) {
      matchedTrack = audioTracks[0];
    }

    if (matchedTrack) {
      matchedTrack.enabled = true;
    }
  }
}

function selectSubtitleTrack(track) {
  selectedSubtitleTrack.value = track;
  showSubtitleMenu.value = false;

  if (!videoElement.value) return;

  // Access textTracks API for subtitle control
  const textTracks = videoElement.value.textTracks;

  if (textTracks && textTracks.length > 0) {
    // Hide all tracks first
    for (let i = 0; i < textTracks.length; i++) {
      textTracks[i].mode = "hidden";
    }

    // Show selected track if one is selected
    if (track) {
      // Try to find matching track by language or index
      let matchedTrack = null;

      // First try to match by language
      if (track.language) {
        for (let i = 0; i < textTracks.length; i++) {
          if (
            textTracks[i].language === track.language.toLowerCase() ||
            textTracks[i].language === track.language
          ) {
            matchedTrack = textTracks[i];
            break;
          }
        }
      }

      // If no language match, try to match by index (subtitles are usually in order)
      if (!matchedTrack && subtitleTracks.value.length === textTracks.length) {
        const trackIndex = subtitleTracks.value.findIndex((t) => t.id === track.id);
        if (trackIndex >= 0 && trackIndex < textTracks.length) {
          matchedTrack = textTracks[trackIndex];
        }
      }

      // If still no match, try the first available track
      if (!matchedTrack && textTracks.length > 0) {
        matchedTrack = textTracks[0];
      }

      if (matchedTrack) {
        matchedTrack.mode = "showing";
      }
    }
  }
}

// Close menus when clicking outside
function toggleAudioMenu() {
  showSubtitleMenu.value = false; // Close subtitle menu when opening audio menu
  showAudioMenu.value = !showAudioMenu.value;
  if (showAudioMenu.value) {
    nextTick(() => {
      setTimeout(() => {
        document.addEventListener("click", closeMenus, { once: true });
      }, 100);
    });
  }
}

function toggleSubtitleMenu() {
  showAudioMenu.value = false; // Close audio menu when opening subtitle menu
  showSubtitleMenu.value = !showSubtitleMenu.value;
  if (showSubtitleMenu.value) {
    nextTick(() => {
      setTimeout(() => {
        document.addEventListener("click", closeMenus, { once: true });
      }, 100);
    });
  }
}

function closeMenus() {
  showAudioMenu.value = false;
  showSubtitleMenu.value = false;
}

function setupAudioTracks() {
  if (!videoElement.value) return;

  // Wait a bit for audioTracks to be available
  nextTick(() => {
    setTimeout(() => {
      const audioTracksList = videoElement.value?.audioTracks;

      if (audioTracksList && audioTracksList.length > 0) {
        // Listen for audio track changes
        audioTracksList.addEventListener("change", () => {
          // Track changes handled silently
        });

        // Select default audio track if available
        const defaultAudio = audioTracks.value.find((t) => t.is_default) || audioTracks.value[0];
        if (defaultAudio) {
          selectAudioTrack(defaultAudio);
        }
      } else {
        // Browser doesn't expose audioTracks API - select default from metadata
        if (audioTracks.value.length > 0) {
          const defaultAudio = audioTracks.value.find((t) => t.is_default) || audioTracks.value[0];
          if (defaultAudio) {
            selectedAudioTrack.value = defaultAudio;
          }
        }
      }
    }, 100);
  });
}

function setupSubtitleTracks() {
  if (!videoElement.value) return;

  // Wait a bit for textTracks to be available
  nextTick(() => {
    setTimeout(() => {
      const textTracks = videoElement.value?.textTracks;

      if (textTracks && textTracks.length > 0) {
        // Hide all tracks initially
        for (let i = 0; i < textTracks.length; i++) {
          textTracks[i].mode = "hidden";
        }

        // If we have a selected subtitle track, show it
        if (selectedSubtitleTrack.value) {
          selectSubtitleTrack(selectedSubtitleTrack.value);
        } else {
          // Otherwise, try to select default subtitle track
          const defaultSubtitle = subtitleTracks.value.find((t) => t.is_default);
          if (defaultSubtitle) {
            selectSubtitleTrack(defaultSubtitle);
          }
        }
      }
    }, 100);
  });
}
</script>

<template>
  <div
    class="custom-video-player relative w-full h-full flex items-center justify-center"
    @mousemove="showControls"
    @mouseleave="hideControls"
  >
    <video
      ref="videoElement"
      :src="videoSrc"
      class="w-full h-full object-contain"
      playsinline
      preload="auto"
      crossorigin="anonymous"
      @loadedmetadata="onLoadedMetadata"
      @timeupdate="onTimeUpdate"
      @play="onPlay"
      @pause="onPause"
      @volumechange="onVolumeChange"
      @error="onError"
      @loadeddata="onLoadedData"
      @playing="onPlaying"
    >
      <!-- Subtitle tracks will be managed via JavaScript textTracks API -->
    </video>

    <!-- Controls Overlay -->
    <div
      v-show="controlsVisible"
      class="controls-overlay absolute inset-0 bg-linear-to-t from-black/80 via-transparent to-transparent flex flex-col justify-end transition-opacity duration-300"
    >
      <!-- Progress Bar -->
      <div class="progress-container px-4 mb-2">
        <div
          ref="progressBar"
          class="progress-bar h-1 bg-gray-600 rounded-full cursor-pointer relative"
          @click="seek"
          @mousemove="onProgressHover"
          @mouseleave="hoverTime = null"
        >
          <div
            class="progress-fill h-full bg-primary-600 rounded-full transition-all"
            :style="{ width: `${progressPercent}%` }"
          ></div>
          <div
            v-if="hoverTime !== null"
            class="hover-time absolute -top-8 text-white text-xs bg-black/80 px-2 py-1 rounded-sm"
            :style="{ left: `${hoverPercent}%` }"
          >
            {{ formatTime(hoverTime) }}
          </div>
        </div>
      </div>

      <!-- Control Bar -->
      <div class="control-bar px-4 pb-4 flex items-center gap-4">
        <!-- Play/Pause Button -->
        <button
          @click="togglePlay"
          class="text-white hover:text-primary-400 transition-colors"
          :aria-label="isPlaying ? $t('player.pause') : $t('player.play')"
        >
          <svg v-if="!isPlaying" class="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
            <path
              d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"
            />
          </svg>
          <svg v-else class="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
            <path
              d="M5.5 3.5A.5.5 0 016 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5zm5 0A.5.5 0 0111 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5z"
            />
          </svg>
        </button>

        <!-- Time Display -->
        <div class="text-white text-sm">
          {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
        </div>

        <!-- Volume Control -->
        <div class="flex items-center gap-2">
          <button
            @click="toggleMute"
            class="text-white hover:text-primary-400 transition-colors"
            :aria-label="isMuted ? $t('player.unmute') : $t('player.mute')"
          >
            <svg
              v-if="isMuted || volume === 0"
              class="w-6 h-6"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fill-rule="evenodd"
                d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zM14.657 2.929a1 1 0 011.414 0A9.972 9.972 0 0119 10a9.972 9.972 0 01-2.929 7.071 1 1 0 01-1.414-1.414A7.971 7.971 0 0017 10c0-2.21-.894-4.208-2.343-5.657a1 1 0 010-1.414zm-2.829 2.828a1 1 0 011.415 0A5.983 5.983 0 0115 10a5.984 5.984 0 01-1.757 4.243 1 1 0 01-1.415-1.415A3.984 3.984 0 0013 10a3.983 3.983 0 00-1.172-2.828 1 1 0 010-1.415z"
                clip-rule="evenodd"
              />
            </svg>
            <svg v-else-if="volume < 0.5" class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
              <path
                fill-rule="evenodd"
                d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zM12.293 7.293a1 1 0 011.414 0L15 8.586l1.293-1.293a1 1 0 111.414 1.414L16.414 10l1.293 1.293a1 1 0 01-1.414 1.414L15 11.414l-1.293 1.293a1 1 0 01-1.414-1.414L13.586 10l-1.293-1.293a1 1 0 010-1.414z"
                clip-rule="evenodd"
              />
            </svg>
            <svg v-else class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
              <path
                fill-rule="evenodd"
                d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zM14.657 2.929a1 1 0 011.414 0A9.972 9.972 0 0119 10a9.972 9.972 0 01-2.929 7.071 1 1 0 01-1.414-1.414A7.971 7.971 0 0017 10c0-2.21-.894-4.208-2.343-5.657a1 1 0 010-1.414zm-2.829 2.828a1 1 0 011.415 0A5.983 5.983 0 0115 10a5.984 5.984 0 01-1.757 4.243 1 1 0 01-1.415-1.415A3.984 3.984 0 0013 10a3.983 3.983 0 00-1.172-2.828 1 1 0 010-1.415z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            :value="volume"
            @input="setVolume"
            class="volume-slider w-24 h-1 bg-gray-600 rounded-lg appearance-none cursor-pointer"
          />
        </div>

        <!-- Audio Track Selection -->
        <div class="relative z-50">
          <button
            @click.stop="toggleAudioMenu"
            class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
          >
            {{ $t('player.audio_tracks') }}
            <span v-if="audioTracks.length > 0" class="ml-1 text-xs"
              >({{ audioTracks.length }})</span
            >
          </button>
          <div
            v-if="showAudioMenu"
            class="absolute bottom-full left-0 mb-2 bg-gray-900 rounded-lg shadow-lg min-w-[200px] max-h-64 overflow-y-auto z-50 border border-gray-700"
            @click.stop
          >
            <div v-if="audioTracks.length === 0" class="px-4 py-2 text-gray-400 text-sm">
              No audio tracks available
            </div>
            <div
              v-for="track in audioTracks"
              v-else
              :key="track.id"
              @click="selectAudioTrack(track)"
              class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
              :class="{ 'bg-primary-600': selectedAudioTrack?.id === track.id }"
            >
              {{ getAudioTrackLabel(track) }}
            </div>
          </div>
        </div>

        <!-- Subtitle Track Selection -->
        <div class="relative z-50">
          <button
            @click.stop="toggleSubtitleMenu"
            class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
          >
            {{ $t('player.subtitles') }}
            <span v-if="subtitleTracks.length > 0" class="ml-1 text-xs"
              >({{ subtitleTracks.length }})</span
            >
          </button>
          <div
            v-if="showSubtitleMenu"
            class="absolute bottom-full left-0 mb-2 bg-gray-900 rounded-lg shadow-lg min-w-[200px] max-h-64 overflow-y-auto z-50 border border-gray-700"
            @click.stop
          >
            <div
              @click="selectSubtitleTrack(null)"
              class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
              :class="{ 'bg-primary-600': selectedSubtitleTrack === null }"
            >
              {{ $t('player.subtitle_off') }}
            </div>
            <div
              v-for="track in subtitleTracks"
              :key="track.id"
              @click="selectSubtitleTrack(track)"
              class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
              :class="{ 'bg-primary-600': selectedSubtitleTrack?.id === track.id }"
            >
              {{ getSubtitleTrackLabel(track) }}
            </div>
          </div>
        </div>

        <!-- Fullscreen Button -->
        <button
          @click="toggleFullscreen"
          class="text-white hover:text-primary-400 transition-colors ml-auto"
          :aria-label="isFullscreen ? $t('player.exit_fullscreen') : $t('player.fullscreen')"
        >
          <svg
            v-if="!isFullscreen"
            class="w-6 h-6"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
            />
          </svg>
          <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>

        <!-- Close Button -->
        <button
          @click="$emit('close')"
          class="text-white hover:text-primary-400 transition-colors"
          aria-label="Close player"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.volume-slider::-webkit-slider-thumb {
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
}

.volume-slider::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: none;
}
</style>
