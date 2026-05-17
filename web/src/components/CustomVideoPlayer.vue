<script setup lang="ts">
import Hls from "hls.js";
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getAccessToken, media } from "@/api/client";
import { useDeviceProfile } from "@/composables/useDeviceProfile";
import {
  defaultAudioStreamIndex,
  type StreamSource,
  startPlaybackJob,
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
const hlsInstance = ref<Hls | null>(null);
const currentJobId = ref<string | null>(null);
const jobStartOffset = ref<number>(0); // Absolute time offset that the current job starts at
const pendingSeek = ref<number | null>(null); // Seek requested while job is starting

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
  const absoluteCurrent = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + currentTime.value : currentTime.value;
  return (absoluteCurrent / duration.value) * 100;
});

const displayCurrentTime = computed(() => {
  return isHlsPlayback.value ? (jobStartOffset.value ?? 0) + currentTime.value : currentTime.value;
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
  const originalResolution = videoTrack ? `${videoTrack.width || 'Unknown'}x${videoTrack.height || 'Unknown'}` : 'Unknown';
  const currentResolution = selectedResolution.value && !selectedResolution.value.is_original
    ? `${selectedResolution.value.width}x${selectedResolution.value.height}`
    : originalResolution;

  return {
    originalResolution,
    currentResolution,
    duration: duration.value,
    bitrate: props.mediaFile?.bitrate
  };
});

const codecInfo = computed(() => {
  const videoTrack = props.mediaFile?.video_tracks?.[0];
  const audioTrack = selectedAudioTrack.value ?
    props.mediaFile?.audio_tracks?.find(t => t.id === selectedAudioTrack.value?.id) :
    props.mediaFile?.audio_tracks?.[0];

  return {
    video: videoTrack ? {
      codec: videoTrack.codec || 'Unknown',
      profile: videoTrack.profile,
      level: videoTrack.level,
      bitDepth: videoTrack.bit_depth
    } : null,
    audio: audioTrack ? {
      codec: audioTrack.codec || 'Unknown',
      channels: audioTrack.channels,
      sampleRate: audioTrack.sample_rate
    } : null
  };
});

// Load volume from localStorage
onMounted(async () => {
  const savedVolume = localStorage.getItem("videoPlayerVolume");
  if (savedVolume !== null) {
    volume.value = parseFloat(savedVolume);
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
  };
}

async function loadSelectedTextSubtitle() {
  if (!selectedSubtitleTrack.value || !isTextSubtitleCodec(selectedSubtitleTrack.value.codec)) {
    return;
  }
  await loadExternalSubtitle(selectedSubtitleTrack.value);
}


async function initializePlayback() {
  if (!props.mediaFile?.id) return;

  isInitializing.value = true;
  isLoading.value = true;
  loadingMessage.value = "Analyzing media...";
  errorMessage.value = "";
  retryCount.value = 0;

  try {
    // Build device profile if not ready
    const deviceProfile = profile.value || (await buildProfile());

    // Get playback info from server - cast to API expected type
    const playbackInfo = await media.getPlaybackInfo(
      props.mediaFile.id,
      deviceProfile as unknown as Parameters<typeof media.getPlaybackInfo>[1],
    );

    if (!playbackInfo.MediaSources?.length) {
      throw new Error("No playback sources available");
    }

    const source = sourceWithBurnedSubtitle(playbackInfo.MediaSources[0] as StreamSource);
    currentSource.value = source as StreamSource;
    playMethod.value = source.PlayMethod as PlaybackMethod;

    // Store available resolutions and transcode reasons
    const rawResolutions = source.AvailableResolutions as Array<Record<string, unknown>>;
    availableResolutions.value = rawResolutions?.map((r: Record<string, unknown>) => ({
      width: r.width as number,
      height: r.height as number,
      label: r.label as string,
      is_original: r.is_original as boolean
    })) || [];
    transcodeReasons.value = source.TranscodeReasons || [];

    // Set initial resolution to original
    if (availableResolutions.value.length > 0) {
      selectedResolution.value = availableResolutions.value.find(r => r.is_original) || availableResolutions.value[0];
    }

    if (source.PlayMethod === "DirectPlay" && source.DirectStreamUrl) {
      // Direct play - use native video element
      await setupDirectPlay(source.DirectStreamUrl);
      if (selectedAudioTrack.value) {
        selectNativeAudioTrack(selectedAudioTrack.value);
      }
      await loadSelectedTextSubtitle();
    } else if (source.TranscodingUrl) {
      // Need HLS (remux or transcode)
      await setupHlsPlayback(source as StreamSource);
      await loadSelectedTextSubtitle();
    } else {
      throw new Error("No valid playback URL available");
    }
  } catch (error) {
    console.error("Playback initialization failed:", error);
    errorMessage.value = `Failed to start playback: ${error instanceof Error ? error.message : "Unknown error"}`;
    isLoading.value = false;

    // Try fallback to direct stream
    await tryFallbackPlayback();
  } finally {
    isInitializing.value = false;
    // Ensure controls are visible after initialization
    if (!isLoading.value) {
      showControls();
    }
  }
}

async function setupDirectPlay(url: string) {
  isHlsPlayback.value = false;
  loadingMessage.value = "Starting direct playback...";

  const token = getAccessToken();
  videoSrc.value = token ? `${url}?api_key=${token}` : url;
  hasSourceSet.value = true;

  await nextTick();
  if (videoElement.value) {
    videoElement.value.muted = false;
    isMuted.value = false;
    videoElement.value.volume = volume.value > 0 ? volume.value : 1;
    videoElement.value.load();
  }
}

async function setupHlsPlayback(source: StreamSource) {
  if (!source.TranscodingUrl) return null;

  isHlsPlayback.value = true;
  loadingMessage.value = source.IsRemuxOnly ? "Starting remux..." : "Starting transcode...";

  try {
    const desiredStart =
      currentTime.value > 0
        ? (isHlsPlayback.value ? (jobStartOffset.value ?? 0) + currentTime.value : currentTime.value)
        : 0;
    const job = await startPlaybackJob({
      mediaId: props.mediaFile.id,
      source: sourceWithBurnedSubtitle(source),
      audioStreamIndex: selectedAudioStreamIndex(),
      subtitleStreamIndex: selectedBurnedSubtitleStreamIndex(),
      startTime: desiredStart,
    });

    currentJobId.value = job.id;

    // Wait for transcoding to be ready and get job status
    const status = await waitForHlsReady(job.id);

    // Track where the job starts in the full timeline
    jobStartOffset.value = status.start_time ?? 0;

    // Setup HLS.js player
    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    await setupHlsPlayer(playlistUrl);

    // If there was a pending seek requested while the job was starting, handle it now
    if (pendingSeek.value !== null) {
      handleSeekForHls(pendingSeek.value);
      pendingSeek.value = null;
    }

    return status;
  } catch (error) {
    console.error("HLS setup failed:", error);
    throw error;
  }
}

type TranscodingJobSchema = TranscodingJob;

async function waitForHlsReady(jobId: string, maxWait = 30000): Promise<TranscodingJobSchema> {
  return waitForHlsReadyService(
    jobId,
    (status) => {
      loadingMessage.value = `Transcoding... ${Math.round(status.progress_percent || 0)}%`;
    },
    maxWait,
  );
}

async function setupHlsPlayer(playlistUrl: string, startPosition?: number) {
  // Cleanup existing HLS instance
  if (hlsInstance.value) {
    hlsInstance.value.destroy();
    hlsInstance.value = null;
  }

  if (!videoElement.value) return;

  // Clear any direct play source
  videoSrc.value = "";
  hasSourceSet.value = true;

  if (Hls.isSupported()) {
    const hlsConfig = {
      debug: false,
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
        if (token && !url.includes("api_key=")) {
          const separator = url.includes("?") ? "&" : "?";
          xhr.open("GET", `${url}${separator}api_key=${token}`, true);
        }
      },
    };

    const hls = new Hls(hlsConfig);

    hlsInstance.value = hls;

    // Track if we should seek when buffer is ready
    let pendingStartPosition = startPosition;

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      isLoading.value = false;
    });

    hls.on(Hls.Events.BUFFER_APPENDED, () => {
      if (pendingStartPosition !== undefined && videoElement.value) {
        const seekPos = pendingStartPosition;
        pendingStartPosition = undefined;

        videoElement.value.currentTime = seekPos;
        videoElement.value.addEventListener('seeked', () => {
          videoElement.value?.play().catch((e) => console.warn("Autoplay blocked:", e));
        }, { once: true });
      } else if (pendingStartPosition === undefined && !videoElement.value?.currentTime) {
        videoElement.value?.play().catch((e) => console.warn("Autoplay blocked:", e));
      }
    });

    hls.on(Hls.Events.ERROR, (_event, data) => {
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
                setTimeout(() => initializePlayback(), backoffDelay);
              } else {
                console.error("Max retries reached, giving up");
                errorMessage.value = "Playback failed after multiple retries. Please try again later.";
                cleanup();
              }
            } else {
              hls.startLoad();
            }
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            hls.recoverMediaError();
            break;
          default:
            errorMessage.value = `Playback error: ${data.details}`;
            cleanup();
        }
      } else {
        // Non-fatal error - try recovery for specific audio issues
        if (data.details?.includes('bufferAppend') && data.sourceBufferName === 'audio') {
          // Try to recover from audio buffer issues
          setTimeout(() => {
            if (hls && !hls.media?.error) {
              hls.recoverMediaError();
            }
          }, 100);
        }
      }
    });

    hls.loadSource(playlistUrl);
    hls.attachMedia(videoElement.value);
  } else if (videoElement.value.canPlayType("application/vnd.apple.mpegurl")) {
    // Native HLS support (Safari)
    videoSrc.value = playlistUrl;
    isLoading.value = false;
  } else {
    throw new Error("HLS is not supported in this browser");
  }
}

async function tryFallbackPlayback() {
  // If playback-info failed, try direct streaming as fallback
  try {
    const directUrl = media.getDirectStreamUrl(props.mediaFile.id);
    await setupDirectPlay(directUrl);
  } catch (fallbackError) {
    console.error("Fallback also failed:", fallbackError);
  }
}

function cleanup() {
  // Stop HLS job if running
  if (currentJobId.value) {
    media.stopHls(currentJobId.value).catch((e) => console.warn("Failed to stop HLS:", e));
    currentJobId.value = null;
  }

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

  // Remove subtitle tracks and clean up blob URLs
  if (videoElement.value) {
    const tracks = videoElement.value.querySelectorAll("track");
    for (const track of tracks) {
      track.remove();
    }
  }
  // Clean up blob URLs
  for (const url of subtitleBlobUrls.value) {
    URL.revokeObjectURL(url);
  }
  subtitleBlobUrls.value = [];
}

// Audio track switching
async function selectAudioTrack(track: AudioTrackOption) {
  selectedAudioTrack.value = track;
  showAudioMenu.value = false;

  if (!isHlsPlayback.value) {
    // For direct play, try native audio track API
    selectNativeAudioTrack(track);
    return;
  }

  // For HLS playback, restart transcode with new audio stream
  const savedTime = currentTime.value;
  isLoading.value = true;
  loadingMessage.value = "Switching audio track...";

  // Convert relative savedTime to absolute startTime when HLS playback is active
  const absoluteStartTime = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + savedTime : savedTime;

  try {
    // Stop current job
    if (currentJobId.value) {
      await media.stopHls(currentJobId.value);
    }

    const source = sourceWithBurnedSubtitle(currentSource.value || { TranscodingType: "audio-only" });
    const job = await startPlaybackJob({
      mediaId: props.mediaFile.id,
      source,
      audioStreamIndex: track.stream_index,
      subtitleStreamIndex: selectedBurnedSubtitleStreamIndex(),
      startTime: absoluteStartTime,
    });

    currentJobId.value = job.id;

    const status = await waitForHlsReady(job.id);
    jobStartOffset.value = status.start_time ?? absoluteStartTime;

    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    await setupHlsPlayer(playlistUrl);
    await loadSelectedTextSubtitle();

    // Note: Backend handles startTime, so playback starts from the right position
  } catch (error) {
    console.error("Audio track switch failed:", error);
    errorMessage.value = "Failed to switch audio track";
    isLoading.value = false;
  }
}

function selectNativeAudioTrack(track: AudioTrackOption) {
  if (!videoElement.value) return;

  // AudioTrackList is not fully typed in all browsers
  const video = videoElement.value as HTMLVideoElement & { audioTracks?: { length: number; [index: number]: { enabled: boolean; language: string } } };
  const audioTrackList = video.audioTracks;
  if (!audioTrackList || audioTrackList.length === 0) return;

  // Disable all tracks first
  for (let i = 0; i < audioTrackList.length; i++) {
    audioTrackList[i].enabled = false;
  }

  // Find and enable matching track
  for (let i = 0; i < audioTrackList.length; i++) {
    const audioTrack = audioTrackList[i];
    if (
      audioTrack.language === track.language?.toLowerCase() ||
      i === track.stream_index
    ) {
      audioTrack.enabled = true;
      break;
    }
  }
}

// Subtitle track switching
async function selectSubtitleTrack(track: SubtitleTrackOption | null) {
  selectedSubtitleTrack.value = track;
  showSubtitleMenu.value = false;

  // Remove existing external subtitle tracks
  if (videoElement.value) {
    const existingTracks = videoElement.value.querySelectorAll("track[data-external]");
    for (const t of existingTracks) {
      // Clean up blob URLs if any
      const src = t.getAttribute('src');
      if (src?.startsWith('blob:')) {
        URL.revokeObjectURL(src);
        subtitleBlobUrls.value = subtitleBlobUrls.value.filter(url => url !== src);
      }
      t.remove();
    }

    // Hide all native tracks
    const textTracks = videoElement.value.textTracks;
    for (let i = 0; i < textTracks.length; i++) {
      textTracks[i].mode = "hidden";
    }
  }

  if (!track) return;

  // Check if it's a text-based subtitle (can be extracted)
  const isTextBased = isTextSubtitleCodec(track.codec);

  if (isTextBased) {
    // Load external WebVTT subtitle
    await loadExternalSubtitle(track);
  } else {
    // Image-based subtitle - need to restart transcode with burning
    await restartWithBurnedSubtitle(track);
  }
}

async function loadExternalSubtitle(track: SubtitleTrackOption) {
  if (!videoElement.value) return;

  const subtitleUrl = media.getSubtitleUrl(props.mediaFile.id, track.stream_index);
  let finalSubtitleUrl = subtitleUrl;

  // If we have a jobStartOffset, we need to adjust the subtitle timestamps
  // Fetch the WebVTT file, adjust timestamps, and create a blob URL
  if (isHlsPlayback.value && jobStartOffset.value > 0) {
    try {
      const token = getAccessToken();
      const urlWithAuth = token ? `${subtitleUrl}${subtitleUrl.includes('?') ? '&' : '?'}api_key=${token}` : subtitleUrl;
      const response = await fetch(urlWithAuth);
      const vttContent = await response.text();
      const offset = jobStartOffset.value;
      const adjustedVtt = adjustWebVttForOffset(vttContent, offset);

      // Create blob URL
      const blob = new Blob([adjustedVtt], { type: 'text/vtt' });
      finalSubtitleUrl = URL.createObjectURL(blob);
      subtitleBlobUrls.value.push(finalSubtitleUrl);
    } catch (error) {
      console.warn("Failed to adjust subtitle timestamps, using original:", error);
      // Fall back to original URL if adjustment fails
    }
  }

  const trackElement = document.createElement("track");
  trackElement.kind = "subtitles";
  trackElement.label = getSubtitleTrackLabel(track);
  trackElement.srclang = track.language || "und";
  trackElement.src = finalSubtitleUrl;
  trackElement.default = true;
  trackElement.setAttribute("data-external", "true");

  videoElement.value.appendChild(trackElement);

  // Wait for track to load and enable it
  trackElement.addEventListener("load", () => {
    if (!videoElement.value) return;
    const textTracks = videoElement.value.textTracks;
    for (let i = 0; i < textTracks.length; i++) {
      if (textTracks[i].label === trackElement.label) {
        textTracks[i].mode = "showing";
        break;
      }
    }
  });
}

async function restartWithBurnedSubtitle(track: SubtitleTrackOption) {
  const savedTime = currentTime.value;

  // Pause playback immediately
  if (videoElement.value) {
    videoElement.value.pause();
  }

  isLoading.value = true;
  loadingMessage.value = "Burning subtitles...";

  const absoluteStartTime = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + savedTime : savedTime;

  try {
    if (currentJobId.value) {
      await media.stopHls(currentJobId.value);
    }

    const source = currentSource.value || { TranscodingType: "full" };
    const job = await startPlaybackJob({
      mediaId: props.mediaFile.id,
      source: { ...source, TranscodingType: "full", IsRemuxOnly: false },
      audioStreamIndex: selectedAudioTrack.value?.stream_index,
      subtitleStreamIndex: track.stream_index,
      startTime: absoluteStartTime,
    });

    currentJobId.value = job.id;
    isHlsPlayback.value = true;
    playMethod.value = "Transcode";

    const status = await waitForHlsReady(job.id);

    // Update job start offset
    jobStartOffset.value = status.start_time ?? absoluteStartTime;

    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    // Calculate relative position within the new job
    const relativePosition = Math.max(0, absoluteStartTime - jobStartOffset.value);
    await setupHlsPlayer(playlistUrl, relativePosition);
  } catch (error) {
    console.error("Subtitle burn failed:", error);
    errorMessage.value = "Failed to burn subtitles";
    isLoading.value = false;
  }
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
      if (!isPlaying.value || isLoading.value) return;
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
  if (!videoElement.value) return;
  if (isHlsPlayback.value && !currentJobId.value) {
    // Job hasn't started yet - remember the desired seek and handle it when the job is ready
    pendingSeek.value = absoluteSeek;
    loadingMessage.value = t("player.seeking_to", { time: formatTime(absoluteSeek) });
    isLoading.value = true;
    return;
  }

  if (!isHlsPlayback.value || !currentJobId.value) {
    // Regular direct play seek
    videoElement.value.currentTime = absoluteSeek;
    return;
  }

  // HLS playback - handle via helper that may restart transcode if needed
  handleSeekForHls(absoluteSeek);
}

/**
 * Handle seeks for HLS playback.
 * - If seek is within current job's transcoded range, seek within the media element
 * - If seek is beyond the transcoded range, stop the current job and start a new one with startTime
 */
async function handleSeekForHls(absoluteSeek: number) {
  if (!currentJobId.value) return;

  // Get job status to assess transcoded_duration
  let status: TranscodingJobSchema | null;
  try {
    status = await media.getHlsStatus(currentJobId.value);
  } catch (err) {
    console.warn("Failed to get hls status for seek, will attempt to start new job", err);
    status = null;
  }

  const jobStart = status?.start_time ?? jobStartOffset.value ?? 0;
  const transcoded = status?.transcoded_duration ?? 0;
  const jobEnd = jobStart + (transcoded || 0);
  const safetyMargin = 2; // seconds

  // If seek is before job start, start a new job from absoluteSeek
  if (absoluteSeek < jobStart + 0.5) {
    // Start a new job at absoluteSeek
    await restartHlsAt(absoluteSeek);
    return;
  }

  // If seek falls within current transcoded range (with margin), just set media time
  if (absoluteSeek <= jobEnd - safetyMargin) {
    // Translate to job-relative time for the media element
    const relativeTime = Math.max(0, absoluteSeek - jobStart);
    if (videoElement.value) {
      videoElement.value.currentTime = relativeTime;

    }
    return;
  }

  // Otherwise, it's beyond what's currently transcoded - restart job from absoluteSeek
  await restartHlsAt(absoluteSeek);
}


async function restartHlsAt(absoluteStart: number) {
  isLoading.value = true;
  loadingMessage.value = t("player.seeking_to", { time: formatTime(absoluteStart) });
  const savedTime = absoluteStart;

  try {
    // Stop current job if any
    if (currentJobId.value) {
      await media.stopHls(currentJobId.value);
    }

    const source = currentSource.value as StreamSource;
    const audioIndex = selectedAudioTrack.value?.stream_index ??
      defaultAudioStreamIndex(audioTracks.value);
    let subtitleIndex: number | undefined ;
    if (selectedSubtitleTrack.value && selectedSubtitleTrack.value.stream_index !== undefined) {
      if (!isTextSubtitleCodec(selectedSubtitleTrack.value.codec)) {
        subtitleIndex = selectedSubtitleTrack.value.stream_index;
      }
    }

    const sourceForJob = subtitleIndex !== undefined
      ? { ...source, TranscodingType: "full", IsRemuxOnly: false }
      : source;
    const job = await startPlaybackJob({
      mediaId: props.mediaFile.id,
      source: sourceForJob,
      audioStreamIndex: audioIndex,
      subtitleStreamIndex: subtitleIndex,
      startTime: savedTime,
    });

    currentJobId.value = job.id;

    // Wait for playlist and status
    const status = await waitForHlsReady(job.id);

    // Update job-start offset
    jobStartOffset.value = status.start_time ?? savedTime;

    // Setup player with the relative position to avoid seek glitch
    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    const relative = Math.max(0, savedTime - jobStartOffset.value);
    await setupHlsPlayer(playlistUrl, relative);

    // Wait for HLS to be stable before re-adding subtitle track
    // This prevents subtitle track addition from triggering HLS reloads
    await new Promise<void>((resolve) => {
      if (!hlsInstance.value) {
        resolve();
        return;
      }

      let resolved = false;
      const onManifestParsed = () => {
        if (!resolved) {
          resolved = true;
          hlsInstance.value?.off(Hls.Events.MANIFEST_PARSED, onManifestParsed);
          // Wait a bit more for HLS to stabilize
          setTimeout(() => resolve(), 500);
        }
      };

      // Check if manifest is already parsed
      if (hlsInstance.value.levels && hlsInstance.value.levels.length > 0) {
        setTimeout(() => resolve(), 500);
      } else {
        hlsInstance.value.on(Hls.Events.MANIFEST_PARSED, onManifestParsed);
        // Timeout after 5 seconds
        setTimeout(() => {
          if (!resolved) {
            resolved = true;
            hlsInstance.value?.off(Hls.Events.MANIFEST_PARSED, onManifestParsed);
            resolve();
          }
        }, 5000);
      }
    });

    // Re-add subtitle track if it was selected (for text-based subtitles)
    // Don't pause/resume - just add the track while playing
    // Pausing can cause timing issues with HLS
    if (selectedSubtitleTrack.value && videoElement.value) {
      const isTextBased = isTextSubtitleCodec(selectedSubtitleTrack.value.codec);
      if (isTextBased) {
        // Always remove existing tracks first to avoid duplicates/conflicts
        const existingTracks = videoElement.value.querySelectorAll("track[data-external]");
        for (const track of existingTracks) {
          // Clean up blob URLs if any
          const src = track.getAttribute('src');
          if (src?.startsWith('blob:')) {
            URL.revokeObjectURL(src);
            subtitleBlobUrls.value = subtitleBlobUrls.value.filter(url => url !== src);
          }
          track.remove();
        }
        // Hide all native tracks
        const textTracks = videoElement.value.textTracks;
        for (let i = 0; i < textTracks.length; i++) {
          textTracks[i].mode = "hidden";
        }
        // Re-add the subtitle track
        await loadExternalSubtitle(selectedSubtitleTrack.value);
      }
    }

  } catch (error) {
    console.error("Failed to restart HLS at seek", error);
    errorMessage.value = t("player.seek_failed");
  } finally {
    isLoading.value = false;
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

  switch (e.key) {
    case " ":
      e.preventDefault();
      togglePlay();
      break;
    case "ArrowLeft":
      e.preventDefault();
      if (isHlsPlayback.value) {
        handleSeekForHls(Math.max(0, (jobStartOffset.value ?? 0) + (videoElement.value?.currentTime ?? 0) - 10));
      } else {
        videoElement.value.currentTime = Math.max(0, videoElement.value.currentTime - 10);
      }
      break;
    case "ArrowRight":
      e.preventDefault();
      if (isHlsPlayback.value) {
        handleSeekForHls(Math.min(duration.value, (jobStartOffset.value ?? 0) + (videoElement.value?.currentTime ?? 0) + 10));
      } else {
        videoElement.value.currentTime = Math.min(duration.value, videoElement.value.currentTime + 10);
      }
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
    videoElement.value.muted = false;
    isMuted.value = false;

    // Set default audio track
    if (!selectedAudioTrack.value && audioTracks.value.length > 0) {
      const defaultAudio = audioTracks.value.find((t: { is_default: boolean }) => t.is_default) || audioTracks.value[0];
      selectedAudioTrack.value = defaultAudio;
    }
    if (!isHlsPlayback.value && selectedAudioTrack.value) {
      selectNativeAudioTrack(selectedAudioTrack.value);
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
  // Show controls when play starts
  showControls();
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
  isLoading.value = true;
  loadingMessage.value = "Format not supported, transcoding...";
  errorMessage.value = "";

  try {
    const job = await startPlaybackJob({
      mediaId: props.mediaFile.id,
      source: sourceWithBurnedSubtitle({ TranscodingType: "full" }),
      audioStreamIndex: selectedAudioStreamIndex(),
      subtitleStreamIndex: selectedBurnedSubtitleStreamIndex(),
    });

    currentJobId.value = job.id;
    isHlsPlayback.value = true;
    playMethod.value = "Transcode";

    const status = await waitForHlsReady(job.id);
    jobStartOffset.value = status.start_time ?? 0;

    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    await setupHlsPlayer(playlistUrl);
    await loadSelectedTextSubtitle();
  } catch (error) {
    console.error("Transcode fallback failed:", error);
    errorMessage.value = "Playback failed. This format may not be supported.";
    isLoading.value = false;
  }
}

function onCanPlay() {
  isLoading.value = false;
}

function onWaiting() {
  isLoading.value = true;
  loadingMessage.value = "Buffering...";
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

async function restartPlaybackWithResolution(requestedResolution: { width: number; height: number } | null) {
  const savedTime = currentTime.value;

  // Pause playback immediately
  if (videoElement.value) {
    videoElement.value.pause();
  }

  isLoading.value = true;
  loadingMessage.value = requestedResolution ?
    `Switching to ${requestedResolution.width}x${requestedResolution.height}...` :
    "Switching to original resolution...";

  try {
    // Stop current job if running
    if (currentJobId.value) {
      await media.stopHls(currentJobId.value);
      currentJobId.value = null;
    }

    // Build device profile and playback request with resolution override
    const deviceProfile = profile.value || (await buildProfile());

    const response = await media.getPlaybackInfo(
      props.mediaFile.id,
      deviceProfile as unknown as Parameters<typeof media.getPlaybackInfo>[1],
      {
        enableDirectPlay: !requestedResolution, // Force transcoding if resolution is specified
        enableDirectStream: !requestedResolution,
        enableTranscoding: true,
        requestedResolution: requestedResolution
      }
    );
    const source = response.MediaSources[0];
    currentSource.value = source as StreamSource;

    playMethod.value = source.PlayMethod as PlaybackMethod;
    transcodeReasons.value = source.TranscodeReasons || [];

    if (source.PlayMethod === "DirectPlay" && source.DirectStreamUrl) {
      await setupDirectPlay(source.DirectStreamUrl);
    } else if (source.TranscodingUrl) {
      const status = await setupHlsPlayback(source as StreamSource);
      // If we started the transcode at a specific offset, seek to the right relative time
      if (savedTime > 0) {
        // If setup returned a job status, it includes start_time
        const jobStart = (status?.start_time) ?? jobStartOffset.value ?? 0;
        setTimeout(() => {
          if (videoElement.value) {
            videoElement.value.currentTime = Math.max(0, savedTime - jobStart);
          }
        }, 1000);
      }
    }

  } catch (error) {
    console.error("Resolution switch failed:", error);
    errorMessage.value = "Failed to switch resolution";
    isLoading.value = false;
  }
}
</script>

<template>
  <div
    class="custom-video-player relative w-full h-full flex items-center justify-center bg-black"
    @mousemove="showControls"
    @mouseleave="hideControls"
    @click="showControls"
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
      :play-method="playMethod"
      @retry="initializePlayback"
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
  </div>
</template>
