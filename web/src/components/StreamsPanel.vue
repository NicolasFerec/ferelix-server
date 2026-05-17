<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type ActiveStream, media, streams as streamsApi } from "@/api/client";

const { t, locale } = useI18n();

const streams = ref<ActiveStream[]>([]);
const loading = ref(false);
const error = ref("");
const stoppingStreams = ref(new Set<string>());
let pollInterval: ReturnType<typeof setInterval> | null = null;

async function loadStreams(showLoading = true) {
  if (showLoading) {
    loading.value = true;
  }
  error.value = "";

  try {
    streams.value = await streamsApi.getActiveStreams();
  } catch (err) {
    console.error("Failed to load streams:", err);
    error.value = err.data?.detail || t("streams.loadFailed");
  } finally {
    if (showLoading) {
      loading.value = false;
    }
  }
}

async function stopStream(streamId: string) {
  const next = new Set(stoppingStreams.value);
  next.add(streamId);
  stoppingStreams.value = next;

  try {
    await streamsApi.stopStream(streamId);
    await loadStreams(false);
  } catch (err) {
    console.error("Failed to stop stream:", err);
    error.value = err.data?.detail || t("streams.stopFailed");
  } finally {
    const updated = new Set(stoppingStreams.value);
    updated.delete(streamId);
    stoppingStreams.value = updated;
  }
}

function formatDate(dateString?: string | null) {
  if (!dateString) return "-";

  try {
    return new Intl.DateTimeFormat(locale.value, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(dateString));
  } catch {
    return dateString;
  }
}

function formatDuration(seconds?: number | null) {
  if (seconds === null || seconds === undefined) return "-";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${remainingSeconds}s`;
  return `${remainingSeconds}s`;
}

function formatBitrate(bitrate?: number | null) {
  if (!bitrate) return "-";
  if (bitrate >= 1_000_000) return `${(bitrate / 1_000_000).toFixed(1)} Mbps`;
  return `${Math.round(bitrate / 1000)} Kbps`;
}

function playbackLabel(stream: ActiveStream) {
  if (stream.play_method === "DirectPlay") return t("streams.playMethods.directPlay");
  if (stream.play_method === "DirectStream") return t("streams.playMethods.directStream");
  if (stream.transcoding_type === "audio-only") return t("streams.playMethods.audioTranscode");
  return t("streams.playMethods.transcode");
}

function decisionLabel(decision?: string | null) {
  switch (decision) {
    case "Direct Play":
      return t("streams.decisions.directPlay");
    case "Direct Stream":
      return t("streams.decisions.directStream");
    case "Transcode":
      return t("streams.decisions.transcode");
    case "Burned in":
      return t("streams.decisions.burnedIn");
    default:
      return decision || "-";
  }
}

function trackSummary(track?: ActiveStream["video"] | ActiveStream["audio"] | ActiveStream["subtitle"] | null) {
  if (!track) return "-";
  const conversion = track.target_label ? `${track.source_label} -> ${track.target_label}` : track.source_label;
  const hardware = track.is_hardware ? ` (${t("streams.hardwareShort")})` : "";
  return `${conversion} - ${decisionLabel(track.decision)}${hardware}`;
}

function userAgentLabel(stream: ActiveStream) {
  if (!stream.user_agent) return t("streams.unknownClient");
  const match = stream.user_agent.match(/(Firefox|Chrome|Safari|Edg|Plex|Ferelix|iPad|iPhone|Android)[/\s]?([0-9.]*)/i);
  return match ? `${match[1]}${match[2] ? ` ${match[2]}` : ""}` : stream.user_agent.slice(0, 42);
}

function progressWidth(stream: ActiveStream) {
  return `${Math.round(stream.progress_percent || 0)}%`;
}

function posterUrl(stream: ActiveStream) {
  return stream.media_file_id ? media.getThumbnailUrl(stream.media_file_id) : "";
}

function initials(name?: string | null) {
  return (name || "?").slice(0, 1).toUpperCase();
}

function streamState(stream: ActiveStream) {
  return stream.is_paused ? t("streams.paused") : t("streams.playing");
}

onMounted(() => {
  loadStreams();
  pollInterval = setInterval(() => loadStreams(false), 3000);
});

onBeforeUnmount(() => {
  if (pollInterval) {
    clearInterval(pollInterval);
  }
});
</script>

<template>
  <div class="streams-panel">
    <div class="mb-8 flex items-center justify-between border-b border-gray-800 pb-6">
      <div>
        <h2 class="text-2xl font-semibold text-white">{{ $t("streams.title") }}</h2>
        <p class="mt-1 text-sm text-gray-400">{{ $t("streams.subtitle") }}</p>
      </div>
      <button
        @click="loadStreams()"
        :disabled="loading"
        class="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-900"
      >
        {{ loading ? $t("common.loading") : $t("streams.refresh") }}
      </button>
    </div>

    <div v-if="error" class="mb-4 rounded-md bg-red-900/40 p-4 text-sm text-red-200">
      {{ error }}
    </div>

    <div v-if="loading && streams.length === 0" class="py-12 text-center text-gray-400">
      {{ $t("common.loading") }}
    </div>

    <div v-else-if="streams.length === 0" class="py-16 text-center text-gray-400">
      {{ $t("streams.empty") }}
    </div>

    <div v-else class="grid gap-6 xl:grid-cols-2 2xl:grid-cols-3">
      <article
        v-for="stream in streams"
        :key="stream.id"
        class="overflow-hidden rounded-md bg-gray-950 shadow-2xl ring-1 ring-white/5"
      >
        <div class="bg-gray-900 p-4">
          <div class="flex gap-4">
            <img
              :src="posterUrl(stream)"
              :alt="stream.media_file_name || ''"
              class="h-28 w-20 flex-none rounded-sm object-cover bg-gray-800"
            />
            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <h3 class="truncate text-base font-medium text-white">{{ stream.media_file_name || stream.id }}</h3>
                  <p class="mt-1 text-sm text-gray-400">{{ streamState(stream) }} · {{ formatDuration(stream.duration) }}</p>
                </div>
                <button
                  @click="stopStream(stream.id)"
                  :disabled="stoppingStreams.has(stream.id)"
                  class="rounded-md bg-red-700 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:bg-gray-700"
                >
                  {{ stoppingStreams.has(stream.id) ? $t("streams.stopping") : $t("streams.stop") }}
                </button>
              </div>
              <div class="mt-5 h-1 rounded-full bg-gray-800">
                <div class="h-1 rounded-full bg-primary-500" :style="{ width: progressWidth(stream) }"></div>
              </div>
              <div class="mt-2 flex justify-between text-xs text-gray-500">
                <span>{{ formatDuration(stream.position_seconds) }}</span>
                <span>{{ Math.round(stream.progress_percent || 0) }}%</span>
              </div>
            </div>
          </div>
        </div>

        <div class="bg-gray-900 px-4 py-3">
          <div class="flex gap-3">
            <div class="flex h-12 w-12 flex-none items-center justify-center rounded bg-gray-950 text-sm font-semibold text-white">
              {{ playbackLabel(stream).slice(0, 2).toUpperCase() }}
            </div>
            <div class="min-w-0 text-sm">
              <div class="text-gray-200">{{ userAgentLabel(stream) }}</div>
              <div class="mt-1 text-xs text-gray-400">
                {{ playbackLabel(stream) }} · {{ stream.client_ip || $t("streams.unknownClient") }} · {{ formatBitrate(stream.current_bitrate) }}
              </div>
              <div class="mt-1 text-xs text-gray-500">
                {{ $t("streams.lastSeen") }} {{ formatDate(stream.last_heartbeat_at) }}
              </div>
            </div>
          </div>
        </div>

        <div class="divide-y divide-white/5 bg-gray-950">
          <div v-if="stream.video" class="grid grid-cols-[4.5rem_1fr] gap-3 px-4 py-3 text-sm">
            <div class="text-gray-500">{{ $t("streams.video") }}</div>
            <div class="text-gray-200">{{ trackSummary(stream.video) }}</div>
          </div>

          <div v-if="stream.audio" class="grid grid-cols-[4.5rem_1fr] gap-3 px-4 py-3 text-sm">
            <div class="text-gray-500">{{ $t("streams.audio") }}</div>
            <div class="text-gray-200">{{ trackSummary(stream.audio) }}</div>
          </div>

          <div v-if="stream.subtitle" class="grid grid-cols-[4.5rem_1fr] gap-3 px-4 py-3 text-sm">
            <div class="text-gray-500">{{ $t("streams.subtitles") }}</div>
            <div class="text-gray-200">{{ trackSummary(stream.subtitle) }}</div>
          </div>
        </div>

        <div class="flex items-center gap-3 bg-gray-950 p-4">
          <div class="flex h-10 w-10 items-center justify-center rounded-full bg-stone-400 text-lg font-medium text-white">
            {{ initials(stream.username) }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm text-gray-200">{{ stream.username }}</div>
          </div>
        </div>

        <details v-if="stream.acceleration" class="border-t border-white/5 bg-gray-950 px-4 py-3 text-xs text-gray-400">
          <summary class="cursor-pointer text-gray-300">{{ $t("streams.technicalDetails") }}</summary>
          <div class="mt-3 space-y-1">
            <div>{{ $t("streams.acceleration") }}: {{ stream.acceleration.summary }}</div>
            <div>{{ $t("streams.videoDecode") }}: {{ stream.acceleration.video_decode }}</div>
            <div>{{ $t("streams.videoEncode") }}: {{ stream.acceleration.video_encode }}</div>
            <div v-if="stream.acceleration.audio_encode">{{ $t("streams.audioEncode") }}: {{ stream.acceleration.audio_encode }}</div>
            <div v-if="stream.acceleration.device">{{ $t("streams.device") }}: {{ stream.acceleration.device }}</div>
            <code
              v-if="stream.acceleration.ffmpeg_command"
              class="mt-2 block max-h-28 overflow-auto whitespace-pre-wrap break-all rounded bg-black/50 p-2 text-gray-300"
            >
              {{ stream.acceleration.ffmpeg_command }}
            </code>
          </div>
        </details>
      </article>
    </div>
  </div>
</template>
