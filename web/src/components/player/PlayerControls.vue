<script setup lang="ts">
import { ref } from "vue";
import {
  type AudioTrackOption,
  type BufferedPercentage,
  formatTime,
  getAudioTrackLabel,
  getSubtitleTrackLabel,
  type ResolutionOption,
  type SubtitleTrackOption,
} from "@/services/playerUi";

const props = defineProps<{
  visible: boolean;
  isPlaying: boolean;
  displayCurrentTime: number;
  duration: number;
  volume: number;
  isMuted: boolean;
  isFullscreen: boolean;
  progressPercent: number;
  hoverTime: number | null;
  hoverPercent: number;
  bufferedPercentages: BufferedPercentage[];
  audioTracks: AudioTrackOption[];
  subtitleTracks: SubtitleTrackOption[];
  availableResolutions: ResolutionOption[];
  selectedAudioTrack: AudioTrackOption | null;
  selectedSubtitleTrack: SubtitleTrackOption | null;
  selectedResolution: ResolutionOption | null;
  selectedResolutionLabel: string;
  showAudioMenu: boolean;
  showSubtitleMenu: boolean;
  showResolutionMenu: boolean;
}>();

const emit = defineEmits<{
  "toggle-play": [];
  seek: [time: number];
  "progress-hover": [time: number];
  "clear-hover": [];
  "set-volume": [event: Event];
  "toggle-mute": [];
  "toggle-audio-menu": [];
  "select-audio-track": [track: AudioTrackOption];
  "toggle-subtitle-menu": [];
  "select-subtitle-track": [track: SubtitleTrackOption | null];
  "toggle-resolution-menu": [];
  "select-resolution": [resolution: ResolutionOption];
  "toggle-info-panel": [];
  "toggle-fullscreen": [];
  close: [];
}>();

const progressBar = ref<HTMLDivElement | null>(null);

function timeFromPointer(event: MouseEvent): number | null {
  if (!progressBar.value || props.duration === 0) {
    return null;
  }

  const rect = progressBar.value.getBoundingClientRect();
  const percent = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  return percent * props.duration;
}

function seek(event: MouseEvent) {
  const time = timeFromPointer(event);
  if (time !== null) {
    emit("seek", time);
  }
}

function onProgressHover(event: MouseEvent) {
  const time = timeFromPointer(event);
  if (time !== null) {
    emit("progress-hover", time);
  }
}
</script>

<template>
  <div
    v-show="visible"
    class="controls-overlay absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent flex flex-col justify-end transition-opacity duration-300"
  >
    <div class="progress-container px-4 mb-2">
      <div
        ref="progressBar"
        class="progress-bar h-1 bg-gray-600 rounded-full cursor-pointer relative"
        @click="seek"
        @mousemove="onProgressHover"
        @mouseleave="$emit('clear-hover')"
      >
        <div
          v-for="(range, index) in bufferedPercentages"
          :key="index"
          class="buffered-fill absolute h-full bg-gray-400 rounded-full pointer-events-none"
          :style="{
            left: `${range.start}%`,
            width: `${range.width}%`
          }"
        />

        <div
          class="progress-fill h-full bg-primary-600 rounded-full transition-all relative z-10"
          :style="{ width: `${progressPercent}%` }"
        />

        <div
          v-if="hoverTime !== null"
          class="hover-time absolute -top-8 text-white text-xs bg-black/80 px-2 py-1 rounded-sm transform -translate-x-1/2 z-20"
          :style="{ left: `${hoverPercent}%` }"
        >
          {{ formatTime(hoverTime) }}
        </div>
      </div>
    </div>

    <div class="control-bar px-4 pb-4 flex items-center gap-4">
      <button
        class="text-white hover:text-primary-400 transition-colors"
        :aria-label="isPlaying ? $t('player.pause') : $t('player.play')"
        @click="$emit('toggle-play')"
      >
        <svg v-if="!isPlaying" class="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
          <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
        </svg>
        <svg v-else class="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
          <path d="M5.5 3.5A.5.5 0 016 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5zm5 0A.5.5 0 0111 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5z" />
        </svg>
      </button>

      <div class="text-white text-sm">
        {{ formatTime(displayCurrentTime) }} / {{ formatTime(duration) }}
      </div>

      <div class="flex items-center gap-2">
        <button
          class="text-white hover:text-primary-400 transition-colors"
          :aria-label="isMuted ? $t('player.unmute') : $t('player.mute')"
          @click="$emit('toggle-mute')"
        >
          <svg v-if="isMuted || volume === 0" class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zM12.293 7.293a1 1 0 011.414 0L15 8.586l1.293-1.293a1 1 0 111.414 1.414L16.414 10l1.293 1.293a1 1 0 01-1.414 1.414L15 11.414l-1.293 1.293a1 1 0 01-1.414-1.414L13.586 10l-1.293-1.293a1 1 0 010-1.414z" clip-rule="evenodd" />
          </svg>
          <svg v-else-if="volume < 0.5" class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zm2.274 4.217a1 1 0 011.414 0 3.984 3.984 0 010 5.414 1 1 0 01-1.414-1.414 1.984 1.984 0 000-2.586 1 1 0 010-1.414z" clip-rule="evenodd" />
          </svg>
          <svg v-else class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M9.383 3.076A1 1 0 0110 4v12a1 1 0 01-1.617.793L4.383 13H2a1 1 0 01-1-1V8a1 1 0 011-1h2.383l4-3.793a1 1 0 011.617.793zM14.657 2.929a1 1 0 011.414 0A9.972 9.972 0 0119 10a9.972 9.972 0 01-2.929 7.071 1 1 0 01-1.414-1.414A7.971 7.971 0 0017 10c0-2.21-.894-4.208-2.343-5.657a1 1 0 010-1.414zm-2.829 2.828a1 1 0 011.415 0A5.983 5.983 0 0115 10a5.984 5.984 0 01-1.757 4.243 1 1 0 01-1.415-1.415A3.984 3.984 0 0013 10a3.983 3.983 0 00-1.172-2.828 1 1 0 010-1.415z" clip-rule="evenodd" />
          </svg>
        </button>
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          :value="volume"
          class="volume-slider w-24 h-1 bg-gray-600 rounded-lg appearance-none cursor-pointer"
          @input="$emit('set-volume', $event)"
        />
      </div>

      <div class="relative z-50">
        <button
          class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
          @click.stop="$emit('toggle-audio-menu')"
        >
          {{ $t('player.audio_tracks') }}
          <span v-if="audioTracks.length > 0" class="ml-1 text-xs">({{ audioTracks.length }})</span>
        </button>
        <div
          v-if="showAudioMenu"
          class="absolute bottom-full left-0 mb-2 bg-gray-900 rounded-lg shadow-lg min-w-[200px] max-h-64 overflow-y-auto z-50 border border-gray-700"
          @click.stop
        >
          <div v-if="audioTracks.length === 0" class="px-4 py-2 text-gray-400 text-sm">
            {{ $t('player.no_audio_tracks') }}
          </div>
          <div
            v-for="track in audioTracks"
            v-else
            :key="track.id"
            class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
            :class="{ 'bg-primary-600': selectedAudioTrack?.id === track.id }"
            @click="$emit('select-audio-track', track)"
          >
            {{ getAudioTrackLabel(track) }}
          </div>
        </div>
      </div>

      <div class="relative z-50">
        <button
          class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
          @click.stop="$emit('toggle-subtitle-menu')"
        >
          {{ $t('player.subtitles') }}
          <span v-if="subtitleTracks.length > 0" class="ml-1 text-xs">({{ subtitleTracks.length }})</span>
        </button>
        <div
          v-if="showSubtitleMenu"
          class="absolute bottom-full left-0 mb-2 bg-gray-900 rounded-lg shadow-lg min-w-[200px] max-h-64 overflow-y-auto z-50 border border-gray-700"
          @click.stop
        >
          <div
            class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
            :class="{ 'bg-primary-600': selectedSubtitleTrack === null }"
            @click="$emit('select-subtitle-track', null)"
          >
            {{ $t('player.subtitle_off') }}
          </div>
          <div
            v-for="track in subtitleTracks"
            :key="track.id"
            class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
            :class="{ 'bg-primary-600': selectedSubtitleTrack?.id === track.id }"
            @click="$emit('select-subtitle-track', track)"
          >
            {{ getSubtitleTrackLabel(track) }}
          </div>
        </div>
      </div>

      <div class="relative z-50">
        <button
          class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
          :disabled="availableResolutions.length <= 1"
          :class="{ 'opacity-50 cursor-not-allowed': availableResolutions.length <= 1 }"
          @click.stop="$emit('toggle-resolution-menu')"
        >
          {{ $t('player.quality') }}
          <span class="ml-1 text-xs">
            ({{ selectedResolutionLabel }})
          </span>
        </button>
        <div
          v-if="showResolutionMenu && availableResolutions.length > 1"
          class="absolute bottom-full left-0 mb-2 bg-gray-900 rounded-lg shadow-lg min-w-[180px] max-h-64 overflow-y-auto z-50 border border-gray-700"
          @click.stop
        >
          <div
            v-for="resolution in availableResolutions"
            :key="`${resolution.width}x${resolution.height}`"
            class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
            :class="{ 'bg-primary-600': selectedResolution?.width === resolution.width && selectedResolution?.height === resolution.height }"
            @click="$emit('select-resolution', resolution)"
          >
            {{ resolution.label }}
          </div>
        </div>
      </div>

      <button
        class="text-white hover:text-primary-400 transition-colors px-2 py-1"
        :title="$t('player.toggle_info_panel')"
        @click="$emit('toggle-info-panel')"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </button>

      <button
        class="text-white hover:text-primary-400 transition-colors ml-auto"
        :aria-label="isFullscreen ? $t('player.exit_fullscreen') : $t('player.fullscreen')"
        @click="$emit('toggle-fullscreen')"
      >
        <svg v-if="!isFullscreen" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
        </svg>
        <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
        </svg>
      </button>

      <button
        class="text-white hover:text-primary-400 transition-colors"
        :aria-label="$t('player.close')"
        @click="$emit('close')"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
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
