/**
 * Device Profile Builder
 *
 * Probes browser capabilities and builds a Jellyfin-compatible device profile
 * that describes what codecs, containers, and quality levels the client supports.
 */

interface CodecSupport {
    video: Record<string, string[]>;
    audio: Record<string, string[]>;
}

export interface HDRSupport {
    hdr10: boolean;
    dolbyVision: boolean;
    hlg: boolean;
    bitDepth10: boolean;
    bitDepth12: boolean;
    wideColorGamut: boolean;
    mediaCapabilitiesApi?: boolean;
}

interface DisplayCapabilities {
    maxWidth: number;
    maxHeight: number;
    devicePixelRatio: number;
    estimatedMaxWidth: number;
    estimatedMaxHeight: number;
}

export interface DirectPlayProfile {
    Type: "Video" | "Audio";
    Container: string;
    VideoCodec?: string;
    AudioCodec?: string;
}

interface ProfileCondition {
    Condition: string;
    Property: string;
    Value: string;
    IsRequired: boolean;
}

interface CodecProfile {
    Type: "Video" | "Audio";
    Codec?: string;
    Conditions: ProfileCondition[];
}

interface TranscodingProfile {
    Type: "Video" | "Audio";
    Container: string;
    VideoCodec?: string;
    AudioCodec?: string;
    Protocol: string;
    EstimateContentLength: boolean;
    EnableMpegtsM2TsMode: boolean;
    TranscodeSeekInfo: string;
    CopyTimestamps: boolean;
    Context: string;
    EnableSubtitlesInManifest?: boolean;
    MaxAudioChannels?: string;
}

interface SubtitleProfile {
    Format: string;
    Method: string;
}

interface DeviceIdentification {
    FriendlyName: string;
    Manufacturer: string;
    ModelName: string;
    ModelDescription: string;
    ModelNumber: string;
    SerialNumber: string;
    ModelUrl: string;
}

interface DebugInfo {
    userAgent: string;
    codecSupport: CodecSupport;
    hdrSupport: HDRSupport;
    displayCaps: DisplayCapabilities;
    timestamp: string;
}

export interface DeviceProfile {
    Name: string;
    Id: string;
    Identification: DeviceIdentification;
    DirectPlayProfiles: DirectPlayProfile[];
    CodecProfiles: CodecProfile[];
    TranscodingProfiles: TranscodingProfile[];
    SubtitleProfiles: SubtitleProfile[];
    _DebugInfo: DebugInfo;
}

/**
 * Probe browser codec support using HTML5 video element canPlayType()
 */
function probeCodecSupport(): CodecSupport {
    const video = document.createElement("video");
    const audio = document.createElement("audio");

    const support: CodecSupport = {
        video: {},
        audio: {},
    };

    // Helper function to normalize canPlayType results
    const canPlay = (result: string): boolean => {
        return result === "probably" || result === "maybe";
    };

    // Test video containers and codecs
    const videoTests = [
        // MP4 container and variants
        { container: "mp4", codec: "h264", mime: 'video/mp4; codecs="avc1.42E01E"' }, // H.264 Baseline
        { container: "mp4", codec: "h264", mime: 'video/mp4; codecs="avc1.4D401F"' }, // H.264 Main
        { container: "mp4", codec: "h264", mime: 'video/mp4; codecs="avc1.64001F"' }, // H.264 High
        { container: "mp4", codec: "h264", mime: 'video/mp4; codecs="avc1.640028"' }, // H.264 High L4.0
        { container: "mp4", codec: "h264", mime: 'video/mp4; codecs="avc1.640032"' }, // H.264 High L5.0
        { container: "mp4", codec: "hevc", mime: 'video/mp4; codecs="hvc1.1.6.L93.90"' }, // HEVC Main
        { container: "mp4", codec: "hevc", mime: 'video/mp4; codecs="hev1.1.6.L93.90"' }, // HEVC Main (hev1)
        { container: "mp4", codec: "av1", mime: 'video/mp4; codecs="av01.0.04M.08"' }, // AV1
        { container: "mp4", codec: "vp9", mime: 'video/mp4; codecs="vp09.00.10.08"' }, // VP9

        // M4V (iTunes/Apple variant of MP4)
        { container: "m4v", codec: "h264", mime: 'video/mp4; codecs="avc1.42E01E"' },
        { container: "m4v", codec: "h264", mime: 'video/mp4; codecs="avc1.64001F"' },

        // MOV (QuickTime) - browsers treat as MP4
        { container: "mov", codec: "h264", mime: 'video/mp4; codecs="avc1.42E01E"' },
        { container: "mov", codec: "h264", mime: 'video/mp4; codecs="avc1.64001F"' },
        { container: "mov", codec: "hevc", mime: 'video/mp4; codecs="hvc1.1.6.L93.90"' },

        // WebM container
        { container: "webm", codec: "vp8", mime: 'video/webm; codecs="vp8"' },
        { container: "webm", codec: "vp9", mime: 'video/webm; codecs="vp9"' },
        { container: "webm", codec: "vp9", mime: 'video/webm; codecs="vp09.00.10.08"' }, // VP9 Profile 0
        { container: "webm", codec: "av1", mime: 'video/webm; codecs="av01.0.04M.08"' }, // AV1

        // Matroska container (MKV) - limited browser support
        { container: "mkv", codec: "h264", mime: 'video/x-matroska; codecs="avc1.42E01E"' },
        { container: "mkv", codec: "hevc", mime: 'video/x-matroska; codecs="hvc1.1.6.L93.90"' },
    ];

    // Test audio codecs
    const audioTests = [
        // MP4 container and variants
        { container: "mp4", codec: "aac", mime: 'audio/mp4; codecs="mp4a.40.2"' }, // AAC-LC
        { container: "mp4", codec: "aac", mime: 'audio/mp4; codecs="mp4a.40.5"' }, // HE-AAC
        { container: "mp4", codec: "ac3", mime: 'audio/mp4; codecs="ac-3"' }, // AC-3
        { container: "mp4", codec: "eac3", mime: 'audio/mp4; codecs="ec-3"' }, // E-AC-3

        // M4V container (treat as MP4 for audio)
        { container: "m4v", codec: "aac", mime: 'audio/mp4; codecs="mp4a.40.2"' },

        // MOV container (treat as MP4 for audio)
        { container: "mov", codec: "aac", mime: 'audio/mp4; codecs="mp4a.40.2"' },
        { container: "mov", codec: "ac3", mime: 'audio/mp4; codecs="ac-3"' },

        // WebM container
        { container: "webm", codec: "opus", mime: 'audio/webm; codecs="opus"' },
        { container: "webm", codec: "vorbis", mime: 'audio/webm; codecs="vorbis"' },

        // Other formats
        { container: "mp3", codec: "mp3", mime: "audio/mpeg" },
        { container: "flac", codec: "flac", mime: "audio/flac" },
        { container: "ogg", codec: "vorbis", mime: 'audio/ogg; codecs="vorbis"' },
    ];

    // Test video codec support
    support.video = {};
    videoTests.forEach((test) => {
        const result = video.canPlayType(test.mime);
        if (canPlay(result)) {
            if (!support.video[test.container]) support.video[test.container] = [];
            if (!support.video[test.container].includes(test.codec)) {
                support.video[test.container].push(test.codec);
            }
        }
    });

    // Test audio codec support
    support.audio = {};
    audioTests.forEach((test) => {
        let result: string;
        // Use video element for container formats, audio element for standalone formats
        if (["mp4", "webm"].includes(test.container)) {
            result = video.canPlayType(test.mime);
        } else {
            result = audio.canPlayType(test.mime);
        }

        if (canPlay(result)) {
            if (!support.audio[test.container]) support.audio[test.container] = [];
            if (!support.audio[test.container].includes(test.codec)) {
                support.audio[test.container].push(test.codec);
            }
        }
    });

    return support;
}

/**
 * Detect HDR and high bit-depth support
 */
function probeHDRSupport(): HDRSupport {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");

    const hdrSupport: HDRSupport = {
        hdr10: false,
        dolbyVision: false,
        hlg: false,
        bitDepth10: false,
        bitDepth12: false,
        wideColorGamut: false,
    };

    // Check for MediaCapabilities API (modern browsers)
    if ("mediaCapabilities" in navigator) {
        hdrSupport.mediaCapabilitiesApi = true;
    }

    // Check WebGL extensions for high bit depth support
    if (gl) {
        const extensions = gl.getSupportedExtensions() || [];

        // Most modern browsers support 10-bit decoding even if WebGL extensions don't indicate it
        // Check for texture formats that indicate 10-bit support or assume support for modern browsers
        hdrSupport.bitDepth10 =
            extensions.some(
                (ext) =>
                    ext.includes("texture_norm16") ||
                    ext.includes("texture_float") ||
                    ext.includes("EXT_color_buffer_half_float"),
            ) || true; // Default to true for modern browsers - most support 10-bit decoding

        // 12-bit is less common, be more conservative
        hdrSupport.bitDepth12 = extensions.some(
            (ext) => ext.includes("texture_norm16") || ext.includes("texture_float"),
        );
    } else {
        // If no WebGL, assume 10-bit support for modern browsers
        hdrSupport.bitDepth10 = true;
        hdrSupport.bitDepth12 = false;
    }

    // Check CSS color-gamut support for wide color
    if (window.CSS && CSS.supports) {
        hdrSupport.wideColorGamut = CSS.supports("color", "color(display-p3 1 0 0)");
    }

    return hdrSupport;
}

/**
 * Get maximum supported resolution and refresh rate
 */
function probeDisplayCapabilities(): DisplayCapabilities {
    const screen: Screen = window.screen || ({} as Screen);

    return {
        maxWidth: screen.width || 1920,
        maxHeight: screen.height || 1080,
        devicePixelRatio: window.devicePixelRatio || 1,
        // Estimate max supported resolution (4K if high DPR or large screen)
        estimatedMaxWidth:
            (screen.width && screen.width > 2560) || (window.devicePixelRatio && window.devicePixelRatio > 2)
                ? 3840
                : 1920,
        estimatedMaxHeight:
            (screen.height && screen.height > 1440) || (window.devicePixelRatio && window.devicePixelRatio > 2)
                ? 2160
                : 1080,
    };
}

/**
 * Build DirectPlayProfiles - formats the client can play natively
 */
function buildDirectPlayProfiles(codecSupport: CodecSupport): DirectPlayProfile[] {
    const profiles: DirectPlayProfile[] = [];

    // Video profiles
    Object.entries(codecSupport.video).forEach(([container, videoCodecs]) => {
        // Find compatible audio codecs for this container
        const audioCodecs = codecSupport.audio[container] || [];

        if (videoCodecs.length > 0 && audioCodecs.length > 0) {
            profiles.push({
                Type: "Video",
                Container: container,
                VideoCodec: videoCodecs.join(","),
                AudioCodec: audioCodecs.join(","),
            });
        }
    });

    // Audio-only profiles
    Object.entries(codecSupport.audio).forEach(([container, audioCodecs]) => {
        if (audioCodecs.length > 0) {
            profiles.push({
                Type: "Audio",
                Container: container,
                AudioCodec: audioCodecs.join(","),
            });
        }
    });

    return profiles;
}

/**
 * Build CodecProfiles - constraints and limitations for specific codecs
 */
function buildCodecProfiles(hdrSupport: HDRSupport, displayCaps: DisplayCapabilities): CodecProfile[] {
    const profiles: CodecProfile[] = [];

    // H.264 constraints
    const h264Conditions: ProfileCondition[] = [
        {
            Condition: "LessThanEqual",
            Property: "VideoLevel",
            Value: "52", // Max H.264 level 5.2
            IsRequired: false,
        },
        {
            Condition: "LessThanEqual",
            Property: "Width",
            Value: displayCaps.estimatedMaxWidth.toString(),
            IsRequired: false,
        },
        {
            Condition: "LessThanEqual",
            Property: "Height",
            Value: displayCaps.estimatedMaxHeight.toString(),
            IsRequired: false,
        },
    ];

    // Add bitrate constraint (estimate based on resolution capability)
    const maxBitrate = displayCaps.estimatedMaxWidth >= 3840 ? 80000000 : 20000000; // 80Mbps for 4K, 20Mbps for 1080p
    h264Conditions.push({
        Condition: "LessThanEqual",
        Property: "VideoBitrate",
        Value: maxBitrate.toString(),
        IsRequired: false,
    });

    profiles.push({
        Type: "Video",
        Codec: "h264",
        Conditions: h264Conditions,
    });

    // HEVC constraints (more restrictive on some browsers)
    const hevcConditions: ProfileCondition[] = [
        {
            Condition: "LessThanEqual",
            Property: "VideoLevel",
            Value: "153", // HEVC level 5.1
            IsRequired: false,
        },
        {
            Condition: "LessThanEqual",
            Property: "Width",
            Value: displayCaps.estimatedMaxWidth.toString(),
            IsRequired: false,
        },
        {
            Condition: "LessThanEqual",
            Property: "Height",
            Value: displayCaps.estimatedMaxHeight.toString(),
            IsRequired: false,
        },
    ];

    // Safari HEVC quirks - only specific codec tags
    const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent);
    if (isSafari) {
        hevcConditions.push({
            Condition: "EqualsAny",
            Property: "VideoCodecTag",
            Value: "hvc1|dvh1", // Only these tags work in Safari
            IsRequired: true,
        });
    }

    profiles.push({
        Type: "Video",
        Codec: "hevc",
        Conditions: hevcConditions,
    });

    // Remove aggressive HDR constraints - let the browser handle HDR gracefully
    // Most browsers will fallback to SDR automatically if HDR isn't supported

    // Only add 10-bit constraints if 10-bit really isn't supported (which is rare)
    if (!hdrSupport.bitDepth10) {
        ["h264", "hevc", "vp9", "av1"].forEach((codec) => {
            profiles.push({
                Type: "Video",
                Codec: codec,
                Conditions: [
                    {
                        Condition: "LessThanEqual",
                        Property: "VideoBitDepth",
                        Value: "8",
                        IsRequired: false, // Make this advisory, not blocking
                    },
                ],
            });
        });
    }

    return profiles;
}

/**
 * Build TranscodingProfiles - fallback configurations when direct play fails
 */
function buildTranscodingProfiles(): TranscodingProfile[] {
    return [
        // Video transcoding fallback
        {
            Type: "Video",
            Container: "mp4",
            VideoCodec: "h264",
            AudioCodec: "aac",
            Protocol: "hls",
            EstimateContentLength: false,
            EnableMpegtsM2TsMode: false,
            TranscodeSeekInfo: "Auto",
            CopyTimestamps: false,
            Context: "Streaming",
            EnableSubtitlesInManifest: false,
            MaxAudioChannels: "8",
        },
        // Audio-only transcoding fallback
        {
            Type: "Audio",
            Container: "mp4",
            AudioCodec: "aac",
            Protocol: "hls",
            EstimateContentLength: false,
            EnableMpegtsM2TsMode: false,
            TranscodeSeekInfo: "Auto",
            CopyTimestamps: false,
            Context: "Streaming",
        },
    ];
}

/**
 * Build complete device profile
 */
export function buildDeviceProfile(): DeviceProfile {
    const codecSupport = probeCodecSupport();
    const hdrSupport = probeHDRSupport();
    const displayCaps = probeDisplayCapabilities();

    console.log("Device capabilities:", {
        codecSupport,
        hdrSupport,
        displayCaps,
    });

    const profile: DeviceProfile = {
        Name: "Ferelix Web Client",
        Id: "ferelix-web",
        Identification: {
            FriendlyName: "Ferelix Web Client",
            Manufacturer: "Ferelix",
            ModelName: "Web Browser",
            ModelDescription: "Web Browser Device Profile",
            ModelNumber: "1.0",
            SerialNumber: "web-client",
            ModelUrl: window.location.origin,
        },

        // Core capability arrays
        DirectPlayProfiles: buildDirectPlayProfiles(codecSupport),
        CodecProfiles: buildCodecProfiles(hdrSupport, displayCaps),
        TranscodingProfiles: buildTranscodingProfiles(),

        // Subtitle profiles
        SubtitleProfiles: [
            {
                Format: "vtt",
                Method: "External",
            },
            {
                Format: "srt",
                Method: "External",
            },
        ],

        // Metadata for debugging
        _DebugInfo: {
            userAgent: navigator.userAgent,
            codecSupport,
            hdrSupport,
            displayCaps,
            timestamp: new Date().toISOString(),
        },
    };

    return profile;
}
