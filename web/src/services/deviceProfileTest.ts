/**
 * Test utility to validate device profile functionality
 */

import { buildDeviceProfile, type DeviceProfile, type DirectPlayProfile } from "./deviceProfile";

export async function testDeviceProfile(): Promise<DeviceProfile> {
    console.log("🧪 Testing Device Profile System...");

    try {
        // Build the profile
        const profile = buildDeviceProfile();

        console.log("✅ Device profile built successfully");
        console.log("📊 Profile Summary:", {
            directPlayProfiles: profile.DirectPlayProfiles.length,
            codecProfiles: profile.CodecProfiles.length,
            transcodingProfiles: profile.TranscodingProfiles.length,
        });

        // Test video codec support
        console.log("\n🎥 Video Codec Support:");
        const videoCodecs = ["h264", "hevc", "vp9", "av1"];
        videoCodecs.forEach((codec) => {
            const supported = profile.DirectPlayProfiles.some(
                (p: DirectPlayProfile) => p.Type === "Video" && p.VideoCodec && p.VideoCodec.includes(codec),
            );
            console.log(`  ${supported ? "✅" : "❌"} ${codec.toUpperCase()}`);
        });

        // Test audio codec support
        console.log("\n🔊 Audio Codec Support:");
        const audioCodecs = ["aac", "mp3", "opus", "ac3"];
        audioCodecs.forEach((codec) => {
            const supported = profile.DirectPlayProfiles.some((p: DirectPlayProfile) => p.AudioCodec?.includes(codec));
            console.log(`  ${supported ? "✅" : "❌"} ${codec.toUpperCase()}`);
        });

        // Test container support
        console.log("\n📦 Container Support:");
        const containers = ["mp4", "webm", "mkv"];
        containers.forEach((container) => {
            const supported = profile.DirectPlayProfiles.some((p: DirectPlayProfile) =>
                p.Container.includes(container),
            );
            console.log(`  ${supported ? "✅" : "❌"} ${container.toUpperCase()}`);
        });

        // HDR capabilities
        console.log("\n🌈 HDR Capabilities:");
        const hdr = profile._DebugInfo.hdrSupport;
        console.log(`  ${hdr.hdr10 ? "✅" : "❌"} HDR10`);
        console.log(`  ${hdr.bitDepth10 ? "✅" : "❌"} 10-bit`);
        console.log(`  ${hdr.wideColorGamut ? "✅" : "❌"} Wide Color Gamut`);
        console.log(`  ${hdr.mediaCapabilitiesApi ? "✅" : "❌"} MediaCapabilities API`);

        // Display info
        console.log("\n📺 Display Info:");
        const display = profile._DebugInfo.displayCaps;
        console.log(`  Screen: ${display.maxWidth}×${display.maxHeight}`);
        console.log(`  Estimated Max: ${display.estimatedMaxWidth}×${display.estimatedMaxHeight}`);
        console.log(`  Device Pixel Ratio: ${display.devicePixelRatio}`);

        // Browser info
        console.log("\n🌐 Browser Info:");
        console.log(`  User Agent: ${navigator.userAgent}`);

        return profile;
    } catch (error) {
        console.error("❌ Device profile test failed:", error);
        throw error;
    }
}

// Auto-run test in development
if (import.meta.env.DEV) {
    // Auto-run the test
    testDeviceProfile().catch(console.error);
}
