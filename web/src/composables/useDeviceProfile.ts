/**
 * Device Profile Composable
 *
 * Provides reactive access to device capabilities and profile generation
 */
import { type ComputedRef, computed, onMounted, type Ref, ref } from "vue";
import {
  buildDeviceProfile,
  type DeviceProfile,
  type DirectPlayProfile,
  type HDRSupport,
} from "../services/deviceProfile";

interface VideoTrack {
  codec?: string;
  width?: number;
  height?: number;
  bit_depth?: number;
}

interface AudioTrack {
  codec?: string;
}

interface MediaInfo {
  video_tracks?: VideoTrack[];
  audio_tracks?: AudioTrack[];
  file_extension?: string;
}

interface DeviceProfileReturn {
  // State
  profile: ComputedRef<DeviceProfile | null>;
  isLoading: ComputedRef<boolean>;
  error: ComputedRef<string | null>;

  // Methods
  buildProfile: () => Promise<DeviceProfile>;
  supportsCodec: (codec: string, type?: "video" | "audio") => boolean;
  supportsContainer: (container: string) => boolean;
  needsTranscoding: (mediaInfo: MediaInfo) => boolean;

  // Computed capabilities
  supportedContainers: ComputedRef<string[]>;
  supportedVideoCodecs: ComputedRef<string[]>;
  supportedAudioCodecs: ComputedRef<string[]>;
  hdrCapabilities: ComputedRef<HDRSupport>;
  maxResolution: ComputedRef<{ width: number; height: number }>;
}

// Global device profile cache
let cachedProfile: DeviceProfile | null = null;
let isProfileBuilt = false;

export function useDeviceProfile(): DeviceProfileReturn {
  const isLoading: Ref<boolean> = ref(!isProfileBuilt);
  const profile: Ref<DeviceProfile | null> = ref(cachedProfile);
  const error: Ref<string | null> = ref(null);

  // Build device profile if not already cached
  const buildProfile = async (): Promise<DeviceProfile> => {
    if (isProfileBuilt && cachedProfile) {
      profile.value = cachedProfile;
      isLoading.value = false;
      return cachedProfile;
    }

    try {
      isLoading.value = true;
      error.value = null;

      // Build profile (may take a few ms due to codec probing)
      const deviceProfile = buildDeviceProfile();

      // Cache the profile
      cachedProfile = deviceProfile;
      profile.value = deviceProfile;
      isProfileBuilt = true;

      console.log("Device profile built:", deviceProfile);

      return deviceProfile;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to build device profile";
      error.value = errorMessage;
      console.error("Failed to build device profile:", err);
      throw err;
    } finally {
      isLoading.value = false;
    }
  };

  // Get supported containers for direct play
  const supportedContainers = computed((): string[] => {
    if (!profile.value?.DirectPlayProfiles) return [];

    return profile.value.DirectPlayProfiles.filter((p: DirectPlayProfile) => p.Type === "Video")
      .map((p: DirectPlayProfile) => p.Container)
      .join(",")
      .split(",")
      .filter(Boolean);
  });

  // Get supported video codecs
  const supportedVideoCodecs = computed((): string[] => {
    if (!profile.value?.DirectPlayProfiles) return [];

    const videoProfiles = profile.value.DirectPlayProfiles.filter(
      (p: DirectPlayProfile) => p.Type === "Video",
    );
    const codecs: Set<string> = new Set();

    for (const p of videoProfiles) {
      if (p.VideoCodec) {
        for (const codec of p.VideoCodec.split(",")) {
          codecs.add(codec.trim());
        }
      }
    }

    return Array.from(codecs);
  });

  // Get supported audio codecs
  const supportedAudioCodecs = computed((): string[] => {
    if (!profile.value?.DirectPlayProfiles) return [];

    const codecs = new Set<string>();

    for (const p of profile.value.DirectPlayProfiles) {
      if (p.AudioCodec) {
        for (const codec of p.AudioCodec.split(",")) {
          codecs.add(codec.trim());
        }
      }
    }

    return Array.from(codecs);
  });

  // Check if a specific codec is supported
  const supportsCodec = (codec: string, type: "video" | "audio" = "video"): boolean => {
    if (type === "video") {
      return supportedVideoCodecs.value.includes(codec);
    } else {
      return supportedAudioCodecs.value.includes(codec);
    }
  };

  // Check if a container format is supported
  const supportsContainer = (container: string): boolean => {
    return supportedContainers.value.includes(container);
  };

  // Get HDR capabilities
  const hdrCapabilities = computed((): HDRSupport => {
    return (
      profile.value?._DebugInfo?.hdrSupport || {
        hdr10: false,
        dolbyVision: false,
        hlg: false,
        bitDepth10: false,
        bitDepth12: false,
        wideColorGamut: false,
      }
    );
  });

  // Get maximum supported resolution
  const maxResolution = computed((): { width: number; height: number } => {
    const displayCaps = profile.value?._DebugInfo?.displayCaps;
    if (!displayCaps) return { width: 1920, height: 1080 };

    return {
      width: displayCaps.estimatedMaxWidth,
      height: displayCaps.estimatedMaxHeight,
    };
  });

  // Check if media would likely need transcoding
  const needsTranscoding = (mediaInfo: MediaInfo): boolean => {
    if (!profile.value || !mediaInfo) return true;

    const { video_tracks = [], audio_tracks = [], file_extension } = mediaInfo;

    // Check container support
    const container = file_extension?.replace(".", "") || "unknown";
    if (!supportsContainer(container)) {
      return true; // Container not supported
    }

    // Check video codec support
    const videoTrack = video_tracks[0];
    if (videoTrack?.codec && !supportsCodec(videoTrack.codec, "video")) {
      return true; // Video codec not supported
    }

    // Check audio codec support
    const audioTrack = audio_tracks[0];
    if (audioTrack?.codec && !supportsCodec(audioTrack.codec, "audio")) {
      return true; // Audio codec not supported
    }

    // Check resolution constraints
    if (videoTrack?.width && videoTrack?.height) {
      const maxRes = maxResolution.value;
      if (videoTrack.width > maxRes.width || videoTrack.height > maxRes.height) {
        return true; // Resolution too high
      }
    }

    // Check HDR constraints
    if (videoTrack?.bit_depth && videoTrack.bit_depth > 8 && !hdrCapabilities.value.bitDepth10) {
      return true; // 10-bit content but no 10-bit support
    }

    return false; // Likely can direct play
  };

  // Auto-build profile on mount
  onMounted(() => {
    buildProfile();
  });

  return {
    // State
    profile: computed(() => profile.value),
    isLoading: computed(() => isLoading.value),
    error: computed(() => error.value),

    // Methods
    buildProfile,
    supportsCodec,
    supportsContainer,
    needsTranscoding,

    // Computed capabilities
    supportedContainers,
    supportedVideoCodecs,
    supportedAudioCodecs,
    hdrCapabilities,
    maxResolution,
  };
}
