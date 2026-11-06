<script setup lang="ts">
import Hls from "hls.js";
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import { getAccessToken, media, playbackSessions } from "@/api/client";
import { useDeviceProfile } from "@/composables/useDeviceProfile";
import {
  createPlaybackOperations,
  defaultAudioStreamIndex,
  type StreamSource,
  startPlaybackJob as startPlaybackJobService,
  type TranscodingJob,
  waitForHlsReady as waitForHlsReadyService,
} from "@/services/playerPlayback";
import {
  type AudioTrackOption,
  formatTime,
  getSubtitleTrackLabel,
  type PlaybackMethod,
  type ResolutionOption,
  type SubtitleTrackOption,
} from "@/services/playerUi";
import { adjustWebVttForOffset, isTextSubtitleCodec } from "@/services/subtitles";
import PlayerInfoPanel from "./PlayerInfoPanel.vue";
import PlayerControls from "./player/PlayerControls.vue";
import PlayerStatusOverlays from "./player/PlayerStatusOverlays.vue";

const props = defineProps({
  mediaFile: {
    type: Object,
    required: true,
  },
  initialAudioStreamIndex: {
    type: Number,
    required: false,
    default: undefined,
  },
  initialSubtitleStreamIndex: {
    type: Number,
    required: false,
    default: undefined,
  },
});

const emit = defineEmits(["close"]);

const { t } = useI18n();
const { profile, buildProfile } = useDeviceProfile();

// Video element and HLS instance refs
const videoElement = ref<HTMLVideoElement | null>(null);
const hlsInstance = shallowRef<Hls | null>(null);
const currentJobId = ref<string | null>(null);
const playbackSessionId = ref<string | null>(null);
const playbackAbort = new AbortController();
const playbackOperations = createPlaybackOperations(playbackAbort.signal);
const transitionPosition = ref<number | null>(null);
let subtitleRequest = 0;
let subtitleAbort: AbortController | undefined;
let appliedBurnedSubtitle: number | undefined;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let heartbeatInFlight = false;
let resumeAfterTransition = true;
let resumeDirectPlayback = false;
function absolutePosition(): number {
  return transitionPosition.value ?? displayCurrentTime.value;
}

async function transitionPlayback(
  position: number,
  message: string,
  operation: (signal: AbortSignal) => Promise<void>,
  errorKey = "player.start_failed",
) {
  if (playbackAbort.signal.aborted) return;
  if (transitionPosition.value === null && hasSourceSet.value) resumeAfterTransition = isPlaying.value;
  transitionPosition.value = position;
  isLoading.value = true;
  isInitializing.value = true;
  loadingMessage.value = message;
  errorMessage.value = "";
  clearTimeout(retryTimer);
  try {
    await playbackOperations.run(async (signal) => {
      try {
        await operation(signal);
        signal.throwIfAborted();
        transitionPosition.value = null;
      } catch (error) {
        if (!signal.aborted) {
          cleanup();
          currentTime.value = position;
          transitionPosition.value = null;
          errorMessage.value = t(errorKey, { error: error instanceof Error ? error.message : t("common.unknown") });
        }
      } finally {
        if (!signal.aborted) {
          isInitializing.value = false;
          showControls();
        }
      }
    });
  } catch (error) {
    if (!(error && typeof error === "object" && "name" in error && error.name === "AbortError")) throw error;
  }
}
const heartbeatTimer = ref<ReturnType<typeof setInterval> | null>(null);
const isEndingPlaybackSession = ref(false);
const jobStartOffset = ref<number>(0); // Absolute time offset that the current job starts at
const pendingInitialSeek = ref<number | null>(null);

// Playback state
const videoSrc = ref("");
const controlsVisible = ref(true);
const controlsTimeout = ref<ReturnType<typeof setTimeout> | null>(null);
const isPlaying = ref(false);
const currentTime = ref(0);
const duration = ref(0);
const volume = ref(1);
const isMuted = ref(false);
const isFullscreen = ref(false);
const hoverTime = ref<number | null>(null);
const bufferedRanges = ref<{ start: number; end: number }[]>([]);
const isLoading = ref(true);
const loadingMessage = ref("");
const errorMessage = ref("");

// Track selection
const showAudioMenu = ref(false);
const showSubtitleMenu = ref(false);
const showResolutionMenu = ref(false);
const selectedAudioTrack = ref<AudioTrackOption | null>(null);
const selectedSubtitleTrack = ref<SubtitleTrackOption | null>(null);
const selectedResolution = ref<ResolutionOption | null>(null);
const availableResolutions = ref<ResolutionOption[]>([]);
const subtitleBlobUrls = ref<string[]>([]); // Track blob URLs for cleanup

// Playback method tracking
const playMethod = ref<PlaybackMethod>("DirectPlay");
const isHlsPlayback = ref(false);
const isInitializing = ref(true); // Flag to prevent error handler during init
const hasSourceSet = ref(false); // Flag to track if a source was ever set
const transcodeReasons = ref<string[]>([]);
const retryCount = ref(0);
const maxRetries = 3;
const currentSource = ref<StreamSource | null>(null);
const preferredSource = ref<StreamSource | null>(null);
let preferredSourceKey: string | null = null;
let activePlaybackKey: string | null = null;

// Info panel
const showInfoPanel = ref(false);

const audioTracks = computed(() => {
  return props.mediaFile?.audio_tracks || [];
});

const subtitleTracks = computed(() => {
  return props.mediaFile?.subtitle_tracks || [];
});

const progressPercent = computed(() => {
  if (duration.value === 0) return 0;
  // For HLS playback, video currentTime is relative to job start, so convert to absolute
  const absoluteCurrent = displayCurrentTime.value;
  return (absoluteCurrent / duration.value) * 100;
});

const displayCurrentTime = computed(() => {
  return transitionPosition.value ?? (isHlsPlayback.value ? jobStartOffset.value + currentTime.value : currentTime.value);
});

const hoverPercent = computed(() => {
  if (duration.value === 0 || hoverTime.value === null) return 0;
  return (hoverTime.value / duration.value) * 100;
});

const bufferedPercentages = computed(() => {
  if (duration.value === 0) return [];

  return bufferedRanges.value.map(range => ({
    start: (range.start / duration.value) * 100,
    width: ((range.end - range.start) / duration.value) * 100
  }));
});

const selectedResolutionLabel = computed(() => {
  if (selectedResolution.value) {
    return selectedResolution.value.label.split(" ")[0];
  }
  return availableResolutions.value.length > 1 ? t("player.select") : t("player.auto");
});

const playbackInfo = computed(() => {
  let displayMethod: string = playMethod.value;

  if (playMethod.value === "Transcode" && currentSource.value) {
    const transcodingType = currentSource.value.TranscodingType || "full";

    if (transcodingType === "audio-only") {
      displayMethod = "Transcode (audio)";
    } else if (transcodingType === "video-only") {
      displayMethod = "Transcode (video)";
    } else if (transcodingType === "full") {
      displayMethod = "Transcode (full)";
    }
  } else if (playMethod.value === "DirectStream" || currentSource.value?.IsRemuxOnly) {
    displayMethod = "DirectStream (remux)";
  }

  return {
    playMethod: displayMethod,
    isRemuxOnly: playMethod.value === "DirectStream"
  };
});

const mediaInfo = computed(() => {
  const videoTrack = props.mediaFile?.video_tracks?.[0];
  const unknown = t("common.unknown");
  const originalResolution = videoTrack ? `${videoTrack.width || unknown}x${videoTrack.height || unknown}` : unknown;
  const currentResolution = selectedResolution.value && !selectedResolution.value.is_original
    ? `${selectedResolution.value.width}x${selectedResolution.value.height}`
    : originalResolution;

  return {
    originalResolution,
    currentResolution,
    duration: duration.value,
    bitrate: props.mediaFile?.bitrate,
  };
});

const codecInfo = computed(() => {
  const videoTrack = props.mediaFile?.video_tracks?.[0];
  const audioTrack = selectedAudioTrack.value
    ? props.mediaFile?.audio_tracks?.find((track) => track.id === selectedAudioTrack.value?.id)
    : props.mediaFile?.audio_tracks?.[0];

  return {
    video: videoTrack ? {
      codec: videoTrack.codec || t("common.unknown"),
      profile: videoTrack.profile,
      level: videoTrack.level,
      bitDepth: videoTrack.bit_depth,
    } : null,
    audio: audioTrack ? {
      codec: audioTrack.codec || t("common.unknown"),
      channels: audioTrack.channels,
      sampleRate: audioTrack.sample_rate,
    } : null,
  };
});

// Load volume from localStorage
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
  playbackAbort.abort();
  clearTimeout(retryTimer);
  stopHeartbeat();
  markPlaybackSessionEnded();
  cleanup();
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

function applyInitialTrackSelection() {
  const initialAudio = audioTracks.value.find(
    (track: AudioTrackOption) => track.stream_index === props.initialAudioStreamIndex,
  );
  selectedAudioTrack.value =
    initialAudio ||
    audioTracks.value.find((track: AudioTrackOption) => track.is_default) ||
    audioTracks.value[0] ||
    null;

  selectedSubtitleTrack.value =
    subtitleTracks.value.find(
      (track: SubtitleTrackOption) => track.stream_index === props.initialSubtitleStreamIndex,
    ) || null;
}

function selectedAudioStreamIndex(): number | undefined {
  return selectedAudioTrack.value?.stream_index ?? defaultAudioStreamIndex(audioTracks.value);
}

function selectedBurnedSubtitleStreamIndex(): number | undefined {
  if (!selectedSubtitleTrack.value || isTextSubtitleCodec(selectedSubtitleTrack.value.codec)) {
    return undefined;
  }
  return selectedSubtitleTrack.value.stream_index;
}

function requestedResolution() {
  const resolution = selectedResolution.value;
  return resolution && !resolution.is_original ? { width: resolution.width, height: resolution.height } : null;
}

function sourceSettingsKey(): string {
  const resolution = requestedResolution();
  return `${selectedAudioStreamIndex() ?? "default"}/${resolution ? `${resolution.width}x${resolution.height}` : "original"}`;
}

function playbackSettingsKey(): string {
  return `${sourceSettingsKey()}/${selectedBurnedSubtitleStreamIndex() ?? "off"}`;
}

async function sourceForCurrentSelection(signal: AbortSignal) {
  if (preferredSource.value && preferredSourceKey === sourceSettingsKey()) return preferredSource.value;
  return requestPlaybackSource(signal, requestedResolution(), isHlsPlayback.value);
}

async function ensurePlaybackSession(signal: AbortSignal) {
  if (playbackSessionId.value || !props.mediaFile?.id) return playbackSessionId.value;

  isEndingPlaybackSession.value = false;
  const session = await playbackSessions.create({
    mediaFileId: props.mediaFile.id,
    durationSeconds: props.mediaFile.duration ?? null,
    audioStreamIndex: selectedAudioStreamIndex() ?? null,
    subtitleStreamIndex: selectedSubtitleTrack.value?.stream_index ?? null,
  });
  if (playbackAbort.signal.aborted) {
    await playbackSessions.end(session.id);
    playbackAbort.signal.throwIfAborted();
  }
  playbackSessionId.value = session.id;
  startHeartbeat();
  signal.throwIfAborted();
  return session.id;
}

function startHeartbeat() {
  if (playbackAbort.signal.aborted || heartbeatTimer.value) return;
  heartbeatTimer.value = setInterval(() => {
    sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
  }, 3000);
}

function stopHeartbeat() {
  if (heartbeatTimer.value) {
    clearInterval(heartbeatTimer.value);
    heartbeatTimer.value = null;
  }
}

async function sendHeartbeat() {
  const sessionId = playbackSessionId.value;
  if (!sessionId || isEndingPlaybackSession.value || heartbeatInFlight) return;
  heartbeatInFlight = true;
  try {
    const response = await playbackSessions.heartbeat(sessionId, {
      positionSeconds: displayCurrentTime.value,
      durationSeconds: duration.value || props.mediaFile?.duration || null,
      isPaused: !isPlaying.value,
      playMethod: playMethod.value,
      transcodingType: currentSource.value?.TranscodingType as string | undefined,
      transcodingJobId: currentJobId.value,
      audioStreamIndex: selectedAudioStreamIndex() ?? null,
      subtitleStreamIndex: selectedSubtitleTrack.value?.stream_index ?? null,
    });
    if (response.kicked && sessionId === playbackSessionId.value && !playbackAbort.signal.aborted) {
      handleAdminKick();
    }
  } finally {
    heartbeatInFlight = false;
  }
}

function handleAdminKick() {
  playbackAbort.abort();
  clearTimeout(retryTimer);
  stopHeartbeat();
  playbackSessionId.value = null;
  errorMessage.value = t("player.kickedByAdmin");
  isLoading.value = false;

  if (videoElement.value) {
    videoElement.value.pause();
    videoElement.value.removeAttribute("src");
    videoElement.value.load();
  }

  cleanup(false);
}

function markPlaybackSessionEnded() {
  if (!playbackSessionId.value) return;
  const sessionId = playbackSessionId.value;
  playbackSessionId.value = null;
  isEndingPlaybackSession.value = true;
  playbackSessions.end(sessionId).catch((error) => console.warn("Failed to end playback session:", error));
}

function getResumePosition(): number {
  const view = props.mediaFile?.user_view;
  const mediaDuration = view?.duration_seconds || props.mediaFile?.duration;
  if (!view || view.watched || !mediaDuration || mediaDuration <= 0) return 0;
  if (view.position_seconds < 10 || view.position_seconds >= mediaDuration - 10) return 0;
  return view.position_seconds;
}

function sourceWithBurnedSubtitle(source: StreamSource): StreamSource {
  if (selectedBurnedSubtitleStreamIndex() === undefined) {
    return source;
  }

  return {
    ...source,
    PlayMethod: "Transcode",
    TranscodingUrl: `/api/v1/hls/${props.mediaFile.id}/start`,
    TranscodingType: "full",
    IsRemuxOnly: false,
    TranscodingVideoCodec: "h264",
    TranscodeSettings: { ...source.TranscodeSettings, VideoCodec: "h264" },
  };
}

async function loadSelectedTextSubtitle() {
  clearExternalSubtitles();
  if (selectedSubtitleTrack.value && isTextSubtitleCodec(selectedSubtitleTrack.value.codec)) {
    await loadExternalSubtitle(selectedSubtitleTrack.value);
  }
}

async function requestPlaybackSource(signal: AbortSignal, resolution = requestedResolution(), forceHls = false) {
  await ensurePlaybackSession(signal);
  signal.throwIfAborted();
  const deviceProfile = profile.value || (await buildProfile());
  signal.throwIfAborted();
  const video = videoElement.value;
  const canSelectNativeAudio = !!video && "audioTracks" in video && video.audioTracks != null;
  const response = await media.getPlaybackInfo(
    props.mediaFile.id,
    deviceProfile as unknown as Parameters<typeof media.getPlaybackInfo>[1],
    {
      enableDirectPlay: !resolution && !forceHls && (
        selectedAudioStreamIndex() === defaultAudioStreamIndex(audioTracks.value) ||
        canSelectNativeAudio
      ),
      enableDirectStream: !resolution,
      requestedResolution: resolution,
      audioStreamIndex: selectedAudioStreamIndex(),
      signal,
    },
  );
  signal.throwIfAborted();
  const source = response.MediaSources?.[0] as StreamSource | undefined;
  if (!source) throw new Error("No playback sources available");
  return source;
}

async function initializePlayback(resetRetries = true) {
  if (!props.mediaFile?.id) return;
  const position = hasSourceSet.value ? absolutePosition() : getResumePosition();
  if (resetRetries) retryCount.value = 0;
  await transitionPlayback(position, t("player.analyzing"), async (signal) => {
    const source = await requestPlaybackSource(signal);
    availableResolutions.value = (source.AvailableResolutions || []).map(r => ({
      width: r.width as number, height: r.height as number,
      label: r.label as string, is_original: r.is_original as boolean,
    }));
    selectedResolution.value ??= availableResolutions.value.find(r => r.is_original) || availableResolutions.value[0] || null;
    await replacePlayback(source, position, signal);
  });
}

async function setupDirectPlay(url: string, position: number, signal: AbortSignal) {
  signal.throwIfAborted();
  isHlsPlayback.value = false;
  jobStartOffset.value = 0;
  currentTime.value = position;
  pendingInitialSeek.value = position;
  resumeDirectPlayback = true;
  const sourceUrl = new URL(url, window.location.origin);
  const token = getAccessToken();
  if (token) sourceUrl.searchParams.set("api_key", token);
  if (playbackSessionId.value) sourceUrl.searchParams.set("session_id", playbackSessionId.value);
  videoSrc.value = `${sourceUrl.pathname}${sourceUrl.search}${sourceUrl.hash}`;
  hasSourceSet.value = true;
  await nextTick();
  signal.throwIfAborted();
  if (videoElement.value) {
    videoElement.value.volume = volume.value;
    videoElement.value.muted = isMuted.value;
    videoElement.value.load();
  }
}

async function replacePlayback(baseSource: StreamSource, position: number, signal: AbortSignal) {
  signal.throwIfAborted();
  const sourceKey = sourceSettingsKey();
  const playbackKey = playbackSettingsKey();
  const previousJob = currentJobId.value;
  currentJobId.value = null;
  activePlaybackKey = null;
  hlsInstance.value?.destroy();
  hlsInstance.value = null;
  videoElement.value?.pause();
  clearExternalSubtitles();
  if (previousJob) await media.stopHls(previousJob);
  signal.throwIfAborted();

  preferredSource.value = baseSource;
  preferredSourceKey = sourceKey;
  const source = sourceWithBurnedSubtitle(baseSource);
  currentSource.value = source;
  playMethod.value = source.PlayMethod as PlaybackMethod;
  transcodeReasons.value = source.TranscodeReasons || [];
  appliedBurnedSubtitle = selectedBurnedSubtitleStreamIndex();
  bufferedRanges.value = [];
  if (source.PlayMethod === "DirectPlay" && source.DirectStreamUrl) {
    await setupDirectPlay(source.DirectStreamUrl, position, signal);
  } else if (source.TranscodingUrl) {
    isHlsPlayback.value = true;
    const job = await startPlaybackJobService({
      mediaId: props.mediaFile.id, source,
      audioStreamIndex: selectedAudioStreamIndex(),
      subtitleStreamIndex: selectedBurnedSubtitleStreamIndex(),
      startTime: position, sessionId: playbackSessionId.value, signal,
    });
    currentJobId.value = job.id;
    try {
      const status = await waitForHlsReadyService(job.id, (status) => {
        loadingMessage.value = t("player.transcodingProgress", { progress: Math.round(status.progress_percent || 0) });
      }, 120000, signal);
      signal.throwIfAborted();
      jobStartOffset.value = status.start_time ?? position;
      currentTime.value = Math.max(0, position - jobStartOffset.value);
      pendingInitialSeek.value = null;
      await setupHlsPlayer(media.getHlsPlaylistUrl(job.id), currentTime.value, signal);
    } catch (error) {
      if (currentJobId.value === job.id) currentJobId.value = null;
      await media.stopHls(job.id).catch((error) => console.warn("Failed to stop HLS:", error));
      throw error;
    }
  } else {
    throw new Error("No valid playback URL available");
  }
  signal.throwIfAborted();
  activePlaybackKey = playbackKey;
  void loadSelectedTextSubtitle();
  sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
}

async function setupHlsPlayer(playlistUrl: string, startPosition: number, signal: AbortSignal) {
  // Cleanup existing HLS instance
  if (hlsInstance.value) {
    hlsInstance.value.destroy();
    hlsInstance.value = null;
  }

  if (!videoElement.value) return;

  // Clear any direct play source
  videoSrc.value = "";
  hasSourceSet.value = true;
  resumeDirectPlayback = false;
  await nextTick();
  signal.throwIfAborted();
  if (!videoElement.value) return;

  if (Hls.isSupported()) {
    const hlsConfig = {
      debug: false,
      autoStartLoad: false,
      enableWorker: true,
      testBandwidth: false,
      lowLatencyMode: false,
      maxBufferLength: 90,
      maxMaxBufferLength: 180,
      maxBufferSize: 60 * 1000 * 1000,
      maxBufferHole: 0.5,
      startLevel: -1,
      enableSoftwareAES: true,
      xhrSetup: (xhr, url) => {
        const token = getAccessToken();
        const authenticatedUrl = new URL(url, window.location.origin);
        if (token && authenticatedUrl.origin === window.location.origin) {
          // Playlists may contain the access token used when the job started.
          // Replace it on every request after the API refreshes the session.
          authenticatedUrl.searchParams.set("api_key", token);
          xhr.open("GET", authenticatedUrl.toString(), true);
        }
      },
    };

    const hls = new Hls(hlsConfig);

    hlsInstance.value = hls;

    // Track if we should seek when buffer is ready
    let pendingStartPosition: number | undefined = startPosition;
    const isCurrent = () => hlsInstance.value === hls && !playbackAbort.signal.aborted;
    let mediaRecoveries = 0;
    let networkRecoveries = 0;

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      if (!isCurrent()) return;
      hls.startLoad(startPosition ?? 0);
      isLoading.value = false;
    });

    hls.on(Hls.Events.BUFFER_APPENDED, () => {
      if (!isCurrent()) return;
      if (pendingStartPosition !== undefined && videoElement.value) {
        const seekPos = pendingStartPosition;
        pendingStartPosition = undefined;

        videoElement.value.currentTime = seekPos;
        if (resumeAfterTransition) videoElement.value.play().catch((e) => console.warn("Autoplay blocked:", e));
      }
    });

    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!isCurrent()) return;
      console.error("HLS error:", data);

      // Log more details about audio buffer errors
      if (data.details?.includes('bufferAppend')) {
        console.error("Buffer append error details:", {
          sourceBufferName: data.sourceBufferName,
          mediaSource: data.parent,
          error: data.error
        });
      }

      if (data.fatal) {
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            // Check if it's a 410 (cancelled job) or empty playlist
            if (data.response?.code === 410 || data.reason === "no EXTM3U delimiter") {
              if (retryCount.value < maxRetries) {
                retryCount.value++;
                const backoffDelay = Math.min(1000 * 2 ** (retryCount.value - 1), 8000);
                clearTimeout(retryTimer);
                retryTimer = setTimeout(() => { if (isCurrent()) void initializePlayback(false); }, backoffDelay);
              } else {
                console.error("Max retries reached, giving up");
                errorMessage.value = t("player.retry_failed");
                cleanup();
              }
            } else {
              if (++networkRecoveries <= maxRetries) hls.startLoad();
              else { errorMessage.value = t("player.retry_failed"); cleanup(); }
            }
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            if (++mediaRecoveries <= maxRetries) hls.recoverMediaError();
            else { errorMessage.value = t("player.retry_failed"); cleanup(); }
            break;
          default:
            errorMessage.value = t("player.playback_error", { error: data.details });
            cleanup();
        }
      }
    });

    hls.loadSource(playlistUrl);
    hls.attachMedia(videoElement.value);
  } else if (videoElement.value.canPlayType("application/vnd.apple.mpegurl")) {
    // Native HLS support (Safari)
    videoSrc.value = playlistUrl;
    pendingInitialSeek.value = startPosition ?? 0;
    resumeDirectPlayback = true;
    isLoading.value = false;
  } else {
    throw new Error("HLS is not supported in this browser");
  }
}


function cleanup(stopCurrentJob = true) {
  clearTimeout(retryTimer);
  clearExternalSubtitles();
  // Stop HLS job if running
  if (stopCurrentJob && currentJobId.value) {
    media.stopHls(currentJobId.value).catch((e) => console.warn("Failed to stop HLS:", e));
  }
  currentJobId.value = null;
  activePlaybackKey = null;

  // Reset job start offset
  jobStartOffset.value = 0;

  // Destroy HLS instance
  if (hlsInstance.value) {
    hlsInstance.value.destroy();
    hlsInstance.value = null;
  }

  // Clear HLS playback flag
  isHlsPlayback.value = false;
  isLoading.value = false;

  // Reset buffered ranges
  bufferedRanges.value = [];

}

// Every stream-changing action uses the same serialized lifecycle.
async function selectAudioTrack(track: AudioTrackOption) {
  selectedAudioTrack.value = track;
  showAudioMenu.value = false;
  if (!isHlsPlayback.value && transitionPosition.value === null && selectNativeAudioTrack(track)) {
    activePlaybackKey = playbackSettingsKey();
    return;
  }
  const position = absolutePosition();
  await transitionPlayback(position, t("player.switchingAudio"), async (signal) => {
    // Re-negotiate the selected audio codec on the server. HLS is needed when
    // the browser cannot switch the direct file's AudioTrackList.
    const source = await requestPlaybackSource(signal, requestedResolution(), true);
    await replacePlayback(source, position, signal);
  }, "player.audio_switch_failed");
}

function selectNativeAudioTrack(track: AudioTrackOption): boolean {
  const video = videoElement.value as (HTMLVideoElement & { audioTracks?: { length: number; [index: number]: { enabled: boolean } } }) | null;
  const tracks = video?.audioTracks;
  // ffprobe indexes include video and subtitle streams; the browser list contains audio only.
  const index = audioTracks.value.findIndex((candidate: AudioTrackOption) => candidate.stream_index === track.stream_index);
  if (!tracks || index < 0 || index >= tracks.length) return false;
  for (let i = 0; i < tracks.length; i++) tracks[i].enabled = i === index;
  return true;
}

function clearExternalSubtitles() {
  subtitleAbort?.abort();
  subtitleRequest++;
  for (const track of videoElement.value?.querySelectorAll("track[data-external]") || []) track.remove();
  for (const url of subtitleBlobUrls.value) URL.revokeObjectURL(url);
  subtitleBlobUrls.value = [];
  const tracks = videoElement.value?.textTracks;
  if (tracks) for (let i = 0; i < tracks.length; i++) tracks[i].mode = "disabled";
}

async function selectSubtitleTrack(track: SubtitleTrackOption | null) {
  selectedSubtitleTrack.value = track;
  showSubtitleMenu.value = false;
  clearExternalSubtitles();
  if (selectedBurnedSubtitleStreamIndex() !== appliedBurnedSubtitle) {
    const position = absolutePosition();
    await transitionPlayback(position, t("player.switchingSubtitles"), async (signal) => {
      const source = await sourceForCurrentSelection(signal);
      await replacePlayback(source, position, signal);
    }, "player.subtitle_burn_failed");
  } else if (track && isTextSubtitleCodec(track.codec)) {
    await loadExternalSubtitle(track);
  }
}

async function loadExternalSubtitle(track: SubtitleTrackOption) {
  if (!videoElement.value) return;

  const request = ++subtitleRequest;
  subtitleAbort?.abort();
  subtitleAbort = new AbortController();
  const video = videoElement.value;
  const offset = jobStartOffset.value;
  const subtitleUrl = media.getSubtitleUrl(props.mediaFile.id, track.stream_index);
  let finalSubtitleUrl = subtitleUrl;

  // If we have a jobStartOffset, we need to adjust the subtitle timestamps
  // Fetch the WebVTT file, adjust timestamps, and create a blob URL
  if (isHlsPlayback.value && jobStartOffset.value > 0) {
    try {
      const response = await fetch(subtitleUrl, { signal: subtitleAbort.signal });
      if (!response.ok) throw new Error("Failed to load subtitles");
      const vttContent = await response.text();
      if (request !== subtitleRequest || playbackAbort.signal.aborted) return;
      const adjustedVtt = adjustWebVttForOffset(vttContent, offset);

      // Create blob URL
      const blob = new Blob([adjustedVtt], { type: 'text/vtt' });
      finalSubtitleUrl = URL.createObjectURL(blob);
      subtitleBlobUrls.value.push(finalSubtitleUrl);
    } catch (error) {
      if (request === subtitleRequest && !playbackAbort.signal.aborted) console.warn("Failed to load subtitles:", error);
      return; // Unshifted subtitles would be out of sync after a seek.
    }
  }

  if (request !== subtitleRequest || playbackAbort.signal.aborted || video !== videoElement.value) return;
  const trackElement = document.createElement("track");
  trackElement.kind = "subtitles";
  trackElement.label = getSubtitleTrackLabel(track);
  trackElement.srclang = track.language || "und";
  trackElement.src = finalSubtitleUrl;
  trackElement.default = true;
  trackElement.setAttribute("data-external", "true");

  video.appendChild(trackElement);

  // Wait for track to load and enable it
  trackElement.addEventListener("load", () => {
    if (request !== subtitleRequest || !trackElement.isConnected) return;
    const textTracks = video.textTracks;
    for (let i = 0; i < textTracks.length; i++) {
      if (textTracks[i].label === trackElement.label) {
        textTracks[i].mode = "showing";
        break;
      }
    }
  });
}

// Control functions
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

function togglePlay() {
  if (!videoElement.value) return;
  if (isPlaying.value) {
    videoElement.value.pause();
  } else {
    videoElement.value.play();
  }
}

function seek(absoluteSeek: number) {
  if (!videoElement.value || !Number.isFinite(absoluteSeek)) return;
  const position = Math.max(0, Math.min(duration.value, absoluteSeek));
  if (!isHlsPlayback.value && transitionPosition.value === null) {
    videoElement.value.currentTime = position;
    return;
  }
  void handleSeekForHls(position);
}

async function handleSeekForHls(position: number) {
  await transitionPlayback(position, t("player.seeking_to", { time: formatTime(position) }), async (signal) => {
    const jobId = currentJobId.value;
    let status: TranscodingJob | undefined;
    if (jobId) {
      try { status = await media.getHlsStatus(jobId, signal); }
      catch { signal.throwIfAborted(); }
    }
    signal.throwIfAborted();
    const jobStart = status?.start_time ?? jobStartOffset.value;
    const jobEnd = jobStart + (status?.transcoded_duration ?? 0);
    if (activePlaybackKey === playbackSettingsKey() && status && ["running", "completed"].includes(status.status) && position >= jobStart && position <= jobEnd - 2) {
      if (videoElement.value) videoElement.value.currentTime = position - jobStart;
      currentTime.value = position - jobStart;
      isLoading.value = false;
    } else {
      const source = await sourceForCurrentSelection(signal);
      await replacePlayback(source, position, signal);
    }
  }, "player.seek_failed");
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

// Video event handlers
function onLoadedMetadata() {
  if (videoElement.value) {
    // For HLS playback, use media file duration instead of videoElement.duration
    // because event playlists only report duration of transcoded segments so far
    if (!isHlsPlayback.value || !props.mediaFile?.duration) {
      duration.value = videoElement.value.duration;
    }
    videoElement.value.muted = isMuted.value;

    // Set default audio track
    if (!selectedAudioTrack.value && audioTracks.value.length > 0) {
      const defaultAudio = audioTracks.value.find((t: { is_default: boolean }) => t.is_default) || audioTracks.value[0];
      selectedAudioTrack.value = defaultAudio;
    }
    if (!isHlsPlayback.value && selectedAudioTrack.value) {
      selectNativeAudioTrack(selectedAudioTrack.value);
    }

    if (pendingInitialSeek.value !== null) {
      videoElement.value.currentTime = pendingInitialSeek.value;
      pendingInitialSeek.value = null;
    }

    // Ensure controls are visible when metadata loads
    showControls();
  }
}

function onTimeUpdate() {
  if (videoElement.value) {
    currentTime.value = videoElement.value.currentTime;
  }
}

function onProgress() {
  if (!videoElement.value) return;

  const buffered = videoElement.value.buffered;
  const ranges: { start: number; end: number }[] = [];

  // Extract all buffered time ranges from the video element
  for (let i = 0; i < buffered.length; i++) {
    const start = buffered.start(i);
    const end = buffered.end(i);

    // For HLS playback, convert relative times to absolute times
    const absoluteStart = isHlsPlayback.value
      ? (jobStartOffset.value ?? 0) + start
      : start;
    const absoluteEnd = isHlsPlayback.value
      ? (jobStartOffset.value ?? 0) + end
      : end;

    ranges.push({
      start: absoluteStart,
      end: absoluteEnd
    });
  }

  bufferedRanges.value = ranges;
}

function onPlay() {
  isPlaying.value = true;
  isLoading.value = false;
  sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
  // Show controls when play starts
  showControls();
}

function onPause() {
  isPlaying.value = false;
  sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
  controlsVisible.value = true;
}

function onVolumeChange() {
  if (videoElement.value) {
    volume.value = videoElement.value.volume;
    isMuted.value = videoElement.value.muted;
  }
}

function onError(e: Event) {
  console.error("Video error:", e);

  // Ignore errors during initialization or if no source was ever set
  if (isInitializing.value || !hasSourceSet.value) {
    return;
  }

  if (!isHlsPlayback.value && videoElement.value?.error) {
    const error = videoElement.value.error;
    console.error("Video error code:", error.code, "message:", error.message);

    // If direct play failed, try transcoding fallback
    if (error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      retryWithTranscoding();
    }
  }
}

async function retryWithTranscoding() {
  const position = absolutePosition();
  await transitionPlayback(position, t("player.transcodingFallback"), async (signal) => {
    await replacePlayback({ PlayMethod: "Transcode", TranscodingType: "full", TranscodingUrl: "/start" }, position, signal);
  }, "player.unsupported_format");
}

function onCanPlay() {
  isLoading.value = false;
  if (resumeDirectPlayback) {
    resumeDirectPlayback = false;
    if (resumeAfterTransition) videoElement.value?.play().catch((error) => console.warn("Autoplay blocked:", error));
  }
}

function onWaiting() {
  isLoading.value = true;
  loadingMessage.value = t("player.buffering");
}

function onPlaying() {
  isLoading.value = false;
  showControls();
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

async function selectResolution(resolution: { width: number; height: number; label: string; is_original: boolean }) {
  if (selectedResolution.value === resolution) return;

  selectedResolution.value = resolution;
  showResolutionMenu.value = false;

  if (resolution.is_original) {
    // Switch back to original resolution - restart with no resolution override
    await restartPlaybackWithResolution(null);
  } else {
    // Request specific resolution - force transcode
    await restartPlaybackWithResolution({
      width: resolution.width,
      height: resolution.height
    });
  }
}

async function restartPlaybackWithResolution(resolution: { width: number; height: number } | null) {
  const position = absolutePosition();
  await transitionPlayback(position, t("player.switchingResolution"), async (signal) => {
    const source = await requestPlaybackSource(signal, resolution);
    await replacePlayback(source, position, signal);
  }, "player.resolution_switch_failed");
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
      @select-audio-track="selectAudioTrack"
      @toggle-subtitle-menu="toggleSubtitleMenu"
      @select-subtitle-track="selectSubtitleTrack"
      @toggle-resolution-menu="toggleResolutionMenu"
      @select-resolution="selectResolution"
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
