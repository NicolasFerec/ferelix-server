<script setup lang="ts">
import Hls from "hls.js";
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { getAccessToken, media } from "@/api/client";
import type { components } from "@/api/types";
import { useDeviceProfile } from "@/composables/useDeviceProfile";
import PlayerInfoPanel from "./PlayerInfoPanel.vue";

// Types for subtitle tracks
interface SubtitleTrack {
  id: number;
  stream_index: number;
  codec: string;
  language?: string;
  title?: string;
  is_forced: boolean;
  is_default: boolean;
}

// Text-based subtitle codecs that can be extracted
const TEXT_SUBTITLE_CODECS = new Set([
  "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"
]);

const props = defineProps({
  mediaFile: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(["close"]);

const { t } = useI18n();
const { profile, buildProfile } = useDeviceProfile();

// Video element and HLS instance refs
const videoElement = ref<HTMLVideoElement | null>(null);
const progressBar = ref<HTMLDivElement | null>(null);
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
const isLoading = ref(true);
const loadingMessage = ref("");
const errorMessage = ref("");

// Track selection
const showAudioMenu = ref(false);
const showSubtitleMenu = ref(false);
const showResolutionMenu = ref(false);
const selectedAudioTrack = ref<{ id: number; stream_index: number } | null>(null);
const selectedSubtitleTrack = ref<SubtitleTrack | null>(null);
const selectedResolution = ref<{ width: number; height: number; label: string; is_original: boolean } | null>(null);
const availableResolutions = ref<Array<{ width: number; height: number; label: string; is_original: boolean }>>([]);

// Playback method tracking
const playMethod = ref<"DirectPlay" | "DirectStream" | "Transcode">("DirectPlay");
const isHlsPlayback = ref(false);
const isInitializing = ref(true); // Flag to prevent error handler during init
const hasSourceSet = ref(false); // Flag to track if a source was ever set
const transcodeReasons = ref<string[]>([]);
const retryCount = ref(0);
const maxRetries = 3;
// Types
interface TranscodeSettings {
  MaxWidth?: number;
  MaxHeight?: number;
}

interface StreamSource {
  PlayMethod?: string;
  TranscodingUrl?: string;
  DirectStreamUrl?: string;
  IsRemuxOnly?: boolean;
  TranscodingType?: string;
  TranscodeReasons?: string[];
  AvailableResolutions?: Array<Record<string, unknown>>;
  TranscodeSettings?: TranscodeSettings;
  [key: string]: unknown; // For other dynamic properties
}

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
  if (!progressBar.value || hoverTime.value === null) return 0;
  return (hoverTime.value / duration.value) * 100;
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

    const source = playbackInfo.MediaSources[0];
    currentSource.value = source as StreamSource;
    playMethod.value = source.PlayMethod as "DirectPlay" | "DirectStream" | "Transcode";

    // Store available resolutions and transcode reasons
    const rawResolutions = source.AvailableResolutions as Array<Record<string, unknown>>;
    availableResolutions.value = rawResolutions?.map((r: Record<string, unknown>) => ({
      width: r.width as number,
      height: r.height as number,
      label: r.label as string,
      is_original: r.is_original as boolean
    })) || [];
    transcodeReasons.value = source.TranscodeReasons || [];

    console.log("Available resolutions:", availableResolutions.value);
    console.log("Transcode reasons:", transcodeReasons.value);

    // Set initial resolution to original
    if (availableResolutions.value.length > 0) {
      selectedResolution.value = availableResolutions.value.find(r => r.is_original) || availableResolutions.value[0];
      console.log("Selected initial resolution:", selectedResolution.value);
    }

    console.log("Playback decision:", {
      method: source.PlayMethod,
      reasons: source.TranscodeReasons,
      isRemuxOnly: source.IsRemuxOnly,
    });

    if (source.PlayMethod === "DirectPlay" && source.DirectStreamUrl) {
      // Direct play - use native video element
      await setupDirectPlay(source.DirectStreamUrl);
    } else if (source.TranscodingUrl) {
      // Need HLS (remux or transcode)
      await setupHlsPlayback(source as StreamSource);
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
    // Determine which endpoint to use based on the TranscodingType flag
    let job: Awaited<ReturnType<typeof media.startRemux>>;
    const defaultAudioIndex = audioTracks.value.find((t: { is_default: boolean }) => t.is_default)?.stream_index ?? 0;

    // Use TranscodingType to determine which endpoint to call
    const transcodingType = source.TranscodingType || "full";

    // Use absolute current time as startTime if user has already progressed
    const desiredStart = currentTime.value > 0 ? (isHlsPlayback.value ? (jobStartOffset.value ?? 0) + currentTime.value : currentTime.value) : 0;

    if (transcodingType === "remux" || source.IsRemuxOnly) {
      job = await media.startRemux(props.mediaFile.id, {
        audioStreamIndex: defaultAudioIndex,
        startTime: desiredStart || undefined,
      });
    } else if (transcodingType === "audio-only") {
      job = await media.startAudioTranscode(props.mediaFile.id, {
        audioStreamIndex: defaultAudioIndex,
        startTime: desiredStart || undefined,
      });
    } else {
      // Full transcoding (video + audio)
      // Extract resolution settings from TranscodeSettings if available
      const transcodeSettings = source.TranscodeSettings;

      // Preserve subtitle selection if user has selected an image-based subtitle
      let subtitleIndex: number | undefined ;
      if (selectedSubtitleTrack.value && selectedSubtitleTrack.value.stream_index !== undefined) {
        const isTextBased = TEXT_SUBTITLE_CODECS.has(selectedSubtitleTrack.value.codec?.toLowerCase() || "");
        // Only pass subtitle index for image-based subtitles (they need burning)
        if (!isTextBased) {
          subtitleIndex = selectedSubtitleTrack.value.stream_index;
        }
      }

      job = await media.startTranscode(props.mediaFile.id, {
        audioStreamIndex: defaultAudioIndex,
        startTime: desiredStart || undefined,
        maxWidth: transcodeSettings?.MaxWidth,
        maxHeight: transcodeSettings?.MaxHeight,
        subtitleStreamIndex: subtitleIndex,
      });
    }

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

type TranscodingJobSchema = components["schemas"]["TranscodingJobSchema"];

async function waitForHlsReady(jobId: string, maxWait = 30000): Promise<TranscodingJobSchema> {
  const startTime = Date.now();
  const pollInterval = 500;

  while (Date.now() - startTime < maxWait) {
    const status = await media.getHlsStatus(jobId);

    if (status.status === "running" || status.status === "completed") {
      loadingMessage.value = `Transcoding... ${Math.round(status.progress_percent || 0)}%`;

      // Wait for playlist to be accessible - poll until it returns 200
      const playlistUrl = media.getHlsPlaylistUrl(jobId);
      let playlistReady = false;
      for (let i = 0; i < 20; i++) {
        try {
          // Use GET with abort to check if playlist is ready (HEAD may not be supported)
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 2000);
          const response = await fetch(playlistUrl, {
            method: "GET",
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (response.ok) {
            playlistReady = true;
            break;
          }
        } catch {
          // Playlist not ready yet or request aborted
        }
        await new Promise((r) => setTimeout(r, 500));
        loadingMessage.value = `Waiting for segments... ${i + 1}/20`;
      }

      if (playlistReady) {
        return status;
      }
      // Continue waiting if playlist not ready yet
    }

    if (status.status === "failed") {
      throw new Error(status.error_message || "Transcoding failed");
    }

    if (status.status === "cancelled") {
      throw new Error("Transcoding was cancelled");
    }

    await new Promise((r) => setTimeout(r, pollInterval));
  }

  throw new Error("Timeout waiting for transcode");
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
    const hls = new Hls({
      debug: false,
      enableWorker: true,
      lowLatencyMode: false,
      backBufferLength: 90,
      maxBufferLength: 30,
      maxMaxBufferLength: 600,
      maxBufferSize: 60 * 1000 * 1000, // 60 MB
      maxBufferHole: 0.5,
      startLevel: -1, // Auto
      // Improved audio handling for transcoding scenarios
      audioPreference: undefined, // Let HLS.js decide
      preferManagedMediaSource: false, // Use standard MediaSource for compatibility
      abrEwmaFastLive: 3, // Faster adaptation for live content
      abrEwmaSlowLive: 9,
      // Better error recovery
      enableSoftwareAES: true,
      xhrSetup: (xhr, url) => {
        // Add auth token to HLS requests
        const token = getAccessToken();
        if (token && !url.includes("api_key=")) {
          const separator = url.includes("?") ? "&" : "?";
          xhr.open("GET", `${url}${separator}api_key=${token}`, true);
        }
      },
    });

    hlsInstance.value = hls;

    // Track if we should seek when buffer is ready
    let pendingStartPosition = startPosition;

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      console.log("HLS manifest parsed");
      isLoading.value = false;
    });

    // Wait for buffer to have data before seeking
    hls.on(Hls.Events.BUFFER_APPENDED, () => {
      if (pendingStartPosition !== undefined && videoElement.value) {
        console.log("Buffer ready, seeking to", pendingStartPosition);
        const seekPos = pendingStartPosition;
        pendingStartPosition = undefined; // Clear pending seek

        videoElement.value.currentTime = seekPos;
        // Use one-time event listener for seeked
        videoElement.value.addEventListener('seeked', () => {
          console.log("Seek completed, starting playback");
          videoElement.value?.play().catch((e) => console.warn("Autoplay blocked:", e));
        }, { once: true });
      } else if (pendingStartPosition === undefined && !videoElement.value?.currentTime) {
        // No pending seek, just play
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
            console.log("Network error, trying to recover...");
            // Check if it's a 410 (cancelled job) or empty playlist
            if (data.response?.code === 410 || data.reason === "no EXTM3U delimiter") {
              if (retryCount.value < maxRetries) {
                retryCount.value++;
                const backoffDelay = Math.min(1000 * 2 ** (retryCount.value - 1), 8000);
                console.log(`Job cancelled or empty playlist, retry ${retryCount.value}/${maxRetries} in ${backoffDelay}ms...`);
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
            console.log("Media error, trying to recover...");
            hls.recoverMediaError();
            break;
          default:
            errorMessage.value = `Playback error: ${data.details}`;
            cleanup();
        }
      } else {
        // Non-fatal error - try recovery for specific audio issues
        if (data.details?.includes('bufferAppend') && data.sourceBufferName === 'audio') {
          console.log("Audio buffer error, attempting recovery...");
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
  console.log("Trying fallback direct stream...");

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

  // Remove subtitle tracks
  if (videoElement.value) {
    const tracks = videoElement.value.querySelectorAll("track");
    for (const track of tracks) {
      track.remove();
    }
  }
}

// Audio track switching
async function selectAudioTrack(track: { id: number; stream_index: number }) {
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

    // Start new job with different audio
    const job = playMethod.value === "DirectStream"
      ? await media.startRemux(props.mediaFile.id, {
          audioStreamIndex: track.stream_index,
          startTime: absoluteStartTime,
        })
      : await media.startAudioTranscode(props.mediaFile.id, {
          audioStreamIndex: track.stream_index,
          startTime: absoluteStartTime,
        });

    currentJobId.value = job.id;

    await waitForHlsReady(job.id);

    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    await setupHlsPlayer(playlistUrl);

    // Note: Backend handles startTime, so playback starts from the right position
  } catch (error) {
    console.error("Audio track switch failed:", error);
    errorMessage.value = "Failed to switch audio track";
    isLoading.value = false;
  }
}

function selectNativeAudioTrack(track: { id: number; stream_index: number; language?: string }) {
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
async function selectSubtitleTrack(track: SubtitleTrack | null) {
  selectedSubtitleTrack.value = track;
  showSubtitleMenu.value = false;

  // Remove existing external subtitle tracks
  if (videoElement.value) {
    const existingTracks = videoElement.value.querySelectorAll("track[data-external]");
    for (const t of existingTracks) {
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
  const isTextBased = TEXT_SUBTITLE_CODECS.has(track.codec?.toLowerCase() || "");

  if (isTextBased) {
    // Load external WebVTT subtitle
    await loadExternalSubtitle(track);
  } else {
    // Image-based subtitle - need to restart transcode with burning
    await restartWithBurnedSubtitle(track);
  }
}

async function loadExternalSubtitle(track: SubtitleTrack) {
  if (!videoElement.value) return;

  const subtitleUrl = media.getSubtitleUrl(props.mediaFile.id, track.stream_index);

  const trackElement = document.createElement("track");
  trackElement.kind = "subtitles";
  trackElement.label = getSubtitleTrackLabel(track);
  trackElement.srclang = track.language || "und";
  trackElement.src = subtitleUrl;
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

async function restartWithBurnedSubtitle(track: SubtitleTrack) {
  if (!isHlsPlayback.value) {
    errorMessage.value = "Image subtitles require transcoding";
    return;
  }

  const savedTime = currentTime.value;

  // Pause playback immediately
  if (videoElement.value) {
    videoElement.value.pause();
  }

  isLoading.value = true;
  loadingMessage.value = "Burning subtitles...";

  // Convert relative savedTime to absolute startTime when HLS playback is active
  const absoluteStartTime = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + savedTime : savedTime;

  try {
    if (currentJobId.value) {
      await media.stopHls(currentJobId.value);
    }

    // Full transcode with subtitle burning
    const job = await media.startTranscode(props.mediaFile.id, {
      audioStreamIndex: selectedAudioTrack.value?.stream_index,
      subtitleStreamIndex: track.stream_index,
      startTime: absoluteStartTime,
    });

    currentJobId.value = job.id;

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

function seek(e: MouseEvent) {
  if (!videoElement.value || !progressBar.value) return;
  const rect = progressBar.value.getBoundingClientRect();
  const percent = (e.clientX - rect.left) / rect.width;
  const absoluteSeek = percent * duration.value;

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

    // Decide which transcode endpoint to call based on currentSource
    const source = currentSource.value as StreamSource;
    // Use currently selected audio track, fallback to default
    const audioIndex = selectedAudioTrack.value?.stream_index ??
      audioTracks.value.find((t: { is_default: boolean }) => t.is_default)?.stream_index ?? 0;

    // Check if we need to burn subtitles (image-based only)
    let needsSubtitleBurning = false;
    let subtitleIndex: number | undefined ;
    if (selectedSubtitleTrack.value && selectedSubtitleTrack.value.stream_index !== undefined) {
      const isTextBased = TEXT_SUBTITLE_CODECS.has(selectedSubtitleTrack.value.codec?.toLowerCase() || "");
      if (!isTextBased) {
        needsSubtitleBurning = true;
        subtitleIndex = selectedSubtitleTrack.value.stream_index;
        console.log("Seek - Need to burn subtitle at stream index:", subtitleIndex);
      }
    }

    let job: TranscodingJobSchema;
    // If subtitle burning is needed, force full transcode
    if (needsSubtitleBurning) {
      const transcodeSettings = source.TranscodeSettings;
      console.log("Seek - Using full transcode due to burned subtitles");
      job = await media.startTranscode(props.mediaFile.id, {
        audioStreamIndex: audioIndex,
        subtitleStreamIndex: subtitleIndex,
        startTime: savedTime,
        maxWidth: transcodeSettings?.MaxWidth,
        maxHeight: transcodeSettings?.MaxHeight,
      });
    } else if (source.IsRemuxOnly || source.TranscodingType === 'remux') {
      job = await media.startRemux(props.mediaFile.id, {
        audioStreamIndex: audioIndex,
        startTime: savedTime
      });
    } else if (source.TranscodingType === 'audio-only') {
      job = await media.startAudioTranscode(props.mediaFile.id, {
        audioStreamIndex: audioIndex,
        startTime: savedTime
      });
    } else {
      // For full transcode without subtitles, preserve resolution settings
      const transcodeSettings = source.TranscodeSettings;
      console.log("Seek - Using full transcode");
      job = await media.startTranscode(props.mediaFile.id, {
        audioStreamIndex: audioIndex,
        subtitleStreamIndex: undefined,
        startTime: savedTime,
        maxWidth: transcodeSettings?.MaxWidth,
        maxHeight: transcodeSettings?.MaxHeight,
      });
    }

    currentJobId.value = job.id;

    // Wait for playlist and status
    const status = await waitForHlsReady(job.id);

    // Update job-start offset
    jobStartOffset.value = status.start_time ?? savedTime;

    // Setup player with the relative position to avoid seek glitch
    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    const relative = Math.max(0, savedTime - jobStartOffset.value);
    await setupHlsPlayer(playlistUrl, relative);

  } catch (error) {
    console.error("Failed to restart HLS at seek", error);
    errorMessage.value = t("player.seek_failed");
  } finally {
    isLoading.value = false;
  }
}

function onProgressHover(e: MouseEvent) {
  if (!progressBar.value || duration.value === 0) return;
  const rect = progressBar.value.getBoundingClientRect();
  const percent = (e.clientX - rect.left) / rect.width;
  hoverTime.value = percent * duration.value;
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

    // Ensure controls are visible when metadata loads
    showControls();
  }
}

function onTimeUpdate() {
  if (videoElement.value) {
    currentTime.value = videoElement.value.currentTime;
  }
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
    console.log("Ignoring video error during initialization");
    return;
  }

  if (!isHlsPlayback.value && videoElement.value?.error) {
    const error = videoElement.value.error;
    console.error("Video error code:", error.code, "message:", error.message);

    // If direct play failed, try transcoding fallback
    if (error.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
      console.log("Direct play not supported, falling back to transcoding...");
      retryWithTranscoding();
    }
  }
}

async function retryWithTranscoding() {
  isLoading.value = true;
  loadingMessage.value = "Format not supported, transcoding...";
  errorMessage.value = "";

  try {
    const job = await media.startTranscode(props.mediaFile.id, {
      audioStreamIndex: selectedAudioTrack.value?.stream_index,
    });

    currentJobId.value = job.id;
    isHlsPlayback.value = true;
    playMethod.value = "Transcode";

    await waitForHlsReady(job.id);

    const playlistUrl = media.getHlsPlaylistUrl(job.id);
    await setupHlsPlayer(playlistUrl);
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
  // Ensure controls are visible when playback actually starts
  showControls();
}

// Utility functions
function formatTime(seconds: number): string {
  if (!seconds || Number.isNaN(seconds)) return "0:00";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function getAudioTrackLabel(track: { language?: string; channels?: number; title?: string; stream_index: number }): string {
  const parts = [];
  if (track.language) {
    parts.push(track.language.toUpperCase());
  }
  if (track.channels) {
    if (track.channels === 2) parts.push("Stereo");
    else if (track.channels === 6) parts.push("5.1");
    else if (track.channels === 8) parts.push("7.1");
    else parts.push(`${track.channels}ch`);
  }
  if (track.title) {
    parts.push(track.title);
  }
  return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
}

function getSubtitleTrackLabel(track: SubtitleTrack): string {
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
  // Indicate if it needs burning
  if (!TEXT_SUBTITLE_CODECS.has(track.codec?.toLowerCase() || "")) {
    parts.push("⚠️");
  }
  return parts.length > 0 ? parts.join(" ") : `Track ${track.stream_index}`;
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

    playMethod.value = source.PlayMethod as "DirectPlay" | "DirectStream" | "Transcode";
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
      @play="onPlay"
      @pause="onPause"
      @volumechange="onVolumeChange"
      @error="onError"
      @canplay="onCanPlay"
      @waiting="onWaiting"
      @playing="onPlaying"
    />

    <!-- Loading Overlay -->
    <div
      v-if="isLoading"
      class="absolute inset-0 flex flex-col items-center justify-center bg-black/60"
    >
      <div class="animate-spin rounded-full h-12 w-12 border-4 border-primary-500 border-t-transparent"></div>
      <p class="mt-4 text-white text-sm">{{ loadingMessage }}</p>
    </div>

    <!-- Error Overlay -->
    <div
      v-if="errorMessage"
      class="absolute inset-0 flex flex-col items-center justify-center bg-black/80"
    >
      <svg class="w-16 h-16 text-red-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      <p class="text-white text-lg mb-4">{{ errorMessage }}</p>
      <button
        @click="initializePlayback"
        class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
      >
        Retry
      </button>
    </div>

    <!-- Playback Method Indicator -->
    <div
      v-if="!isLoading && !errorMessage"
      class="absolute top-4 left-4 px-2 py-1 bg-black/50 rounded text-xs text-white/70"
    >
      {{ playMethod }}{{ playMethod === 'DirectStream' ? ' (Remux)' : '' }}
    </div>

    <!-- Controls Overlay -->
    <div
      v-show="controlsVisible && !errorMessage"
      class="controls-overlay absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent flex flex-col justify-end transition-opacity duration-300"
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
          />
          <div
            v-if="hoverTime !== null"
            class="hover-time absolute -top-8 text-white text-xs bg-black/80 px-2 py-1 rounded-sm transform -translate-x-1/2"
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
            <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
          </svg>
          <svg v-else class="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
            <path d="M5.5 3.5A.5.5 0 016 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5zm5 0A.5.5 0 0111 4v12a.5.5 0 01-1 0V4a.5.5 0 01.5-.5z" />
          </svg>
        </button>

        <!-- Time Display -->
        <div class="text-white text-sm">
          {{ formatTime(displayCurrentTime) }} / {{ formatTime(duration) }}
        </div>

        <!-- Volume Control -->
        <div class="flex items-center gap-2">
          <button
            @click="toggleMute"
            class="text-white hover:text-primary-400 transition-colors"
            :aria-label="isMuted ? $t('player.unmute') : $t('player.mute')"
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
            <span v-if="audioTracks.length > 0" class="ml-1 text-xs">({{ audioTracks.length }})</span>
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
            <span v-if="subtitleTracks.length > 0" class="ml-1 text-xs">({{ subtitleTracks.length }})</span>
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

        <!-- Resolution Selection -->
        <div class="relative z-50">
          <button
            @click.stop="toggleResolutionMenu"
            class="text-white hover:text-primary-400 transition-colors px-3 py-1 text-sm"
            :disabled="availableResolutions.length <= 1"
            :class="{ 'opacity-50 cursor-not-allowed': availableResolutions.length <= 1 }"
          >
            Quality
            <span class="ml-1 text-xs">
              ({{ selectedResolution ? selectedResolution.label.split(' ')[0] : availableResolutions.length > 1 ? 'Select' : 'Auto' }})
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
              @click="selectResolution(resolution)"
              class="px-4 py-2 hover:bg-gray-800 cursor-pointer text-white text-sm"
              :class="{ 'bg-primary-600': selectedResolution?.width === resolution.width && selectedResolution?.height === resolution.height }"
            >
              {{ resolution.label }}
            </div>
          </div>
        </div>

        <!-- Info Panel Toggle -->
        <button
          @click="toggleInfoPanel"
          class="text-white hover:text-primary-400 transition-colors px-2 py-1"
          title="Toggle info panel"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </button>

        <!-- Fullscreen Button -->
        <button
          @click="toggleFullscreen"
          class="text-white hover:text-primary-400 transition-colors ml-auto"
          :aria-label="isFullscreen ? $t('player.exit_fullscreen') : $t('player.fullscreen')"
        >
          <svg v-if="!isFullscreen" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
          <svg v-else class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" />
          </svg>
        </button>

        <!-- Close Button -->
        <button
          @click="$emit('close')"
          class="text-white hover:text-primary-400 transition-colors"
          aria-label="Close player"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>

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
