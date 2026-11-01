<template>
  <div v-if="isVisible" class="info-panel">
    <div class="info-panel-header">
      <h3>{{ $t("player.info.title") }}</h3>
      <button @click="$emit('toggle')" class="close-btn" :title="$t('player.info.close')">
        ✕
      </button>
    </div>

    <div class="info-panel-content">
      <!-- Playback Method -->
      <div class="info-section">
        <h4>{{ $t("player.info.playbackMethod") }}</h4>
        <div class="info-value">{{ playbackInfo?.playMethod || $t("common.unknown") }}</div>
        <div v-if="playbackInfo?.isRemuxOnly" class="info-detail">
          {{ $t("player.info.remuxOnly") }}
        </div>
      </div>

      <!-- Media Information -->
      <div v-if="mediaInfo" class="info-section">
        <h4>{{ $t("player.info.mediaInformation") }}</h4>
        <div class="info-row">
          <span class="label">{{ $t("player.info.originalResolution") }}</span>
          <span class="value">{{ mediaInfo.originalResolution }}</span>
        </div>
        <div v-if="mediaInfo.currentResolution && mediaInfo.currentResolution !== mediaInfo.originalResolution" class="info-row">
          <span class="label">{{ $t("player.info.currentResolution") }}</span>
          <span class="value">{{ mediaInfo.currentResolution }}</span>
        </div>
        <div v-if="mediaInfo.duration" class="info-row">
          <span class="label">{{ $t("player.info.duration") }}</span>
          <span class="value">{{ formatDuration(mediaInfo.duration) }}</span>
        </div>
        <div v-if="mediaInfo.bitrate" class="info-row">
          <span class="label">{{ $t("player.info.bitrate") }}</span>
          <span class="value">{{ formatBitrate(mediaInfo.bitrate) }}</span>
        </div>
      </div>

      <!-- Video Codec Information -->
      <div v-if="codecInfo?.video" class="info-section">
        <h4>{{ $t("player.info.video") }}</h4>
        <div class="info-row">
          <span class="label">{{ $t("player.info.codec") }}</span>
          <span class="value">{{ codecInfo.video.codec }}</span>
        </div>
        <div v-if="codecInfo.video.profile" class="info-row">
          <span class="label">{{ $t("player.info.profile") }}</span>
          <span class="value">{{ codecInfo.video.profile }}</span>
        </div>
        <div v-if="codecInfo.video.level" class="info-row">
          <span class="label">{{ $t("player.info.level") }}</span>
          <span class="value">{{ codecInfo.video.level }}</span>
        </div>
        <div v-if="codecInfo.video.bitDepth" class="info-row">
          <span class="label">{{ $t("player.info.bitDepth") }}</span>
          <span class="value">{{ $t("player.info.bitDepthValue", { depth: codecInfo.video.bitDepth }) }}</span>
        </div>
      </div>

      <!-- Audio Codec Information -->
      <div v-if="codecInfo?.audio" class="info-section">
        <h4>{{ $t("player.info.audio") }}</h4>
        <div class="info-row">
          <span class="label">{{ $t("player.info.codec") }}</span>
          <span class="value">{{ codecInfo.audio.codec }}</span>
        </div>
        <div v-if="codecInfo.audio.channels" class="info-row">
          <span class="label">{{ $t("player.info.channels") }}</span>
          <span class="value">{{ formatChannels(codecInfo.audio.channels) }}</span>
        </div>
        <div v-if="codecInfo.audio.sampleRate" class="info-row">
          <span class="label">{{ $t("player.info.sampleRate") }}</span>
          <span class="value">{{ codecInfo.audio.sampleRate }} Hz</span>
        </div>
      </div>

      <!-- Transcode Reasons -->
      <div v-if="transcodeReasons && transcodeReasons.length > 0" class="info-section">
        <h4>{{ $t("player.info.transcodeReasons") }}</h4>
        <ul class="reason-list">
          <li v-for="reason in transcodeReasons" :key="reason" class="reason-item">
            {{ reason }}
          </li>
        </ul>
      </div>

      <!-- Active Job Information -->
      <div v-if="currentJobId" class="info-section">
        <h4>{{ $t("player.info.transcodingJob") }}</h4>
        <div class="info-row">
          <span class="label">{{ $t("player.info.jobId") }}</span>
          <span class="value">{{ currentJobId }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";

const { t } = useI18n();

interface PlaybackInfo {
  playMethod: string;
  isRemuxOnly?: boolean;
}

interface MediaInfo {
  originalResolution: string;
  currentResolution?: string;
  duration?: number;
  bitrate?: number;
}

interface CodecInfo {
  video?: {
    codec: string;
    profile?: string;
    level?: string;
    bitDepth?: number;
  };
  audio?: {
    codec: string;
    channels?: number;
    sampleRate?: number;
  };
}

defineProps<{
  isVisible: boolean;
  playbackInfo?: PlaybackInfo;
  mediaInfo?: MediaInfo;
  codecInfo?: CodecInfo;
  transcodeReasons?: string[];
  currentJobId?: string;
}>();

defineEmits<{
  toggle: [];
}>();

const formatDuration = (seconds: number): string => {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${remainingSeconds.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
};

const formatBitrate = (bitrate: number): string => {
  const mbps = bitrate / 1000000;
  if (mbps >= 1) {
    return `${mbps.toFixed(1)} Mbps`;
  }
  return `${(bitrate / 1000).toFixed(0)} Kbps`;
};

const formatChannels = (channels: number): string => {
  const channelMap: Record<number, string> = {
    1: "1.0 (Mono)",
    2: "2.0 (Stereo)",
    6: "5.1 (Surround)",
    8: "7.1 (Surround)",
  };
  return channelMap[channels] || t("player.info.channelsValue", { channels });
};
</script>

<style scoped>
.info-panel {
  position: absolute;
  bottom: 60px;
  right: 20px;
  width: 320px;
  background: rgba(0, 0, 0, 0.9);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: white;
  font-size: 12px;
  z-index: 100;
  backdrop-filter: blur(10px);
}

.info-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.info-panel-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.close-btn:hover {
  color: white;
  background: rgba(255, 255, 255, 0.1);
}

.info-panel-content {
  padding: 16px;
  max-height: 400px;
  overflow-y: auto;
}

.info-section {
  margin-bottom: 16px;
}

.info-section:last-child {
  margin-bottom: 0;
}

.info-section h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
  font-weight: 600;
  color: #60a5fa;
}

.info-value {
  font-weight: 600;
  color: #10b981;
}

.info-detail {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.7);
  margin-top: 4px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  gap: 8px;
}

.info-row .label {
  color: rgba(255, 255, 255, 0.7);
  flex-shrink: 0;
}

.info-row .value {
  color: white;
  font-weight: 500;
  text-align: right;
  word-break: break-word;
}

.reason-list {
  margin: 0;
  padding-left: 16px;
}

.reason-item {
  margin-bottom: 4px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.8);
}

.reason-item:last-child {
  margin-bottom: 0;
}

/* Scrollbar styling */
.info-panel-content::-webkit-scrollbar {
  width: 4px;
}

.info-panel-content::-webkit-scrollbar-track {
  background: transparent;
}

.info-panel-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
}

.info-panel-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.5);
}
</style>
