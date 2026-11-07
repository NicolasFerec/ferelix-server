import Hls from "hls.js";
import { computed, nextTick, onUnmounted, type Ref, ref, shallowRef } from "vue";
import { useI18n } from "vue-i18n";
import { type MediaAccess, type MediaFile, media, mediaSessionUrl, playbackSessions } from "@/api/client";
import { useDeviceProfile } from "@/composables/useDeviceProfile";
import {
    createPlaybackOperations,
    defaultAudioStreamIndex,
    playbackMutation,
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

export interface PlayerProps {
    mediaFile: MediaFile;
    initialVideoStreamIndex?: number;
    initialAudioStreamIndex?: number;
    initialSubtitleStreamIndex?: number;
}

/** Owns the playback session, stream transitions, HLS instance and subtitle resources. */
export function usePlayerPlayback(
    props: PlayerProps,
    videoElement: Ref<HTMLVideoElement | null>,
    volume: Ref<number>,
    isMuted: Ref<boolean>,
    onControls: () => void,
) {
    const { t } = useI18n();
    const { profile, buildProfile } = useDeviceProfile();

    const hlsInstance = shallowRef<Hls | null>(null);

    const currentJobId = ref<string | null>(null);

    const playbackSessionId = ref<string | null>(null);
    const mediaAccess = shallowRef<MediaAccess>();
    const canRetry = ref(true);
    let playbackGeneration = 0;
    let mediaSourceRevision = 0;
    let initialTracksResolved = false;
    let audioSelectionExplicit = props.initialAudioStreamIndex !== undefined;
    let subtitleSelectionExplicit = props.initialSubtitleStreamIndex !== undefined;
    const selectedVideoTrack = computed(
        () =>
            props.mediaFile.video_tracks?.find((track) => track.stream_index === props.initialVideoStreamIndex) ||
            props.mediaFile.video_tracks?.find((track) => track.is_default) ||
            props.mediaFile.video_tracks?.[0],
    );

    const playbackAbort = new AbortController();

    const playbackOperations = createPlaybackOperations(playbackAbort.signal);

    const transitionPosition = ref<number | null>(null);

    let subtitleRequest = 0;

    let subtitleAbort: AbortController | undefined;

    let appliedBurnedSubtitle: number | undefined;

    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    let heartbeatInFlight = false;

    const requestedPlaying = ref(true);

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
                        errorMessage.value = t(errorKey, {
                            error: error instanceof Error ? error.message : t("common.unknown"),
                        });
                    }
                } finally {
                    if (!signal.aborted) {
                        isInitializing.value = false;
                        onControls();
                    }
                }
            });
        } catch (error) {
            if (!(error && typeof error === "object" && "name" in error && error.name === "AbortError")) throw error;
        }
    }

    const heartbeatTimer = ref<ReturnType<typeof setInterval> | null>(null);

    const isEndingPlaybackSession = ref(false);

    const jobStartOffset = ref<number>(0);

    const pendingInitialSeek = ref<number | null>(null);

    const videoSrc = ref("");

    const isPlaying = ref(false);

    const currentTime = ref(0);

    const duration = ref(0);

    const bufferedRanges = ref<{ start: number; end: number }[]>([]);

    const isLoading = ref(true);

    const loadingMessage = ref("");

    const errorMessage = ref("");

    const selectedAudioTrack = ref<AudioTrackOption | null>(null);

    const selectedSubtitleTrack = ref<SubtitleTrackOption | null>(null);

    const selectedResolution = ref<ResolutionOption | null>(null);

    const availableResolutions = ref<ResolutionOption[]>([]);

    const subtitleBlobUrls = ref<string[]>([]);

    const playMethod = ref<PlaybackMethod>("DirectPlay");

    const isHlsPlayback = ref(false);

    const isInitializing = ref(true);

    const hasSourceSet = ref(false);

    const transcodeReasons = ref<string[]>([]);

    const retryCount = ref(0);

    const maxRetries = 3;

    const currentSource = ref<StreamSource | null>(null);

    const preferredSource = ref<StreamSource | null>(null);

    let preferredSourceKey: string | null = null;

    let activePlaybackKey: string | null = null;

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
        return (
            transitionPosition.value ??
            (isHlsPlayback.value ? jobStartOffset.value + currentTime.value : currentTime.value)
        );
    });

    const bufferedPercentages = computed(() => {
        if (duration.value === 0) return [];

        return bufferedRanges.value.map((range) => ({
            start: (range.start / duration.value) * 100,
            width: ((range.end - range.start) / duration.value) * 100,
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
            isRemuxOnly: playMethod.value === "DirectStream",
        };
    });

    const mediaInfo = computed(() => {
        const videoTrack = selectedVideoTrack.value;
        const unknown = t("common.unknown");
        const originalResolution = videoTrack
            ? `${videoTrack.width || unknown}x${videoTrack.height || unknown}`
            : unknown;
        const currentResolution =
            selectedResolution.value && !selectedResolution.value.is_original
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
        const videoTrack = selectedVideoTrack.value;
        const audioTrack = selectedAudioTrack.value
            ? props.mediaFile?.audio_tracks?.find((track) => track.id === selectedAudioTrack.value?.id)
            : props.mediaFile?.audio_tracks?.[0];

        return {
            video: videoTrack
                ? {
                      codec: videoTrack.codec || t("common.unknown"),
                      profile: videoTrack.profile,
                      level: videoTrack.level,
                      bitDepth: videoTrack.bit_depth,
                  }
                : null,
            audio: audioTrack
                ? {
                      codec: audioTrack.codec || t("common.unknown"),
                      channels: audioTrack.channels,
                      sampleRate: audioTrack.sample_rate,
                  }
                : null,
        };
    });

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
        return `${selectedVideoTrack.value?.stream_index ?? "default"}/${selectedAudioStreamIndex() ?? "default"}/${resolution ? `${resolution.width}x${resolution.height}` : "original"}/${selectedBurnedSubtitleStreamIndex() ?? "off"}`;
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
        const session = await playbackMutation(
            (requestSignal) =>
                playbackSessions.create(
                    {
                        mediaFileId: props.mediaFile.id,
                        videoStreamIndex: selectedVideoTrack.value?.stream_index,
                        durationSeconds: props.mediaFile.duration ?? null,
                        audioStreamIndex: selectedAudioStreamIndex() ?? null,
                        subtitleStreamIndex: selectedSubtitleTrack.value?.stream_index ?? null,
                    },
                    requestSignal,
                ),
            invalidateUnknownSession,
        );
        if (playbackAbort.signal.aborted) {
            await playbackSessions.end(session.id);
            playbackAbort.signal.throwIfAborted();
        }
        playbackSessionId.value = session.id;
        mediaAccess.value = { sessionId: session.id, token: session.media_access_token };
        playbackGeneration = 0;
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
                playbackGeneration,
                durationSeconds: duration.value || props.mediaFile?.duration || null,
                isPaused: !isPlaying.value,
                playMethod: playMethod.value,
                transcodingType: currentSource.value?.TranscodingType as string | undefined,
                transcodingJobId: currentJobId.value,
                audioStreamIndex: selectedAudioStreamIndex() ?? null,
                videoStreamIndex: selectedVideoTrack.value?.stream_index ?? null,
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
        canRetry.value = false;
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

    function invalidateUnknownSession() {
        // Stop renewing the lease and revoke the whole session: a timed-out POST may
        // already have started an encoder whose job ID never reached this browser.
        canRetry.value = false;
        playbackAbort.abort();
        stopHeartbeat();
        markPlaybackSessionEnded();
        cleanup();
        errorMessage.value = t("player.sessionUnknown");
    }

    function markPlaybackSessionEnded() {
        if (!playbackSessionId.value) return;
        const sessionId = playbackSessionId.value;
        playbackSessionId.value = null;
        isEndingPlaybackSession.value = true;
        playbackSessions
            .end(sessionId, AbortSignal.timeout(10000))
            .catch((error) => console.warn("Failed to end playback session:", error));
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
                enableDirectPlay:
                    !resolution &&
                    !forceHls &&
                    selectedVideoTrack.value?.stream_index ===
                        (
                            props.mediaFile.video_tracks?.find((track) => track.is_default) ||
                            props.mediaFile.video_tracks?.[0]
                        )?.stream_index &&
                    (selectedAudioStreamIndex() === defaultAudioStreamIndex(audioTracks.value) || canSelectNativeAudio),
                enableDirectStream: !resolution,
                requestedResolution: resolution,
                audioStreamIndex:
                    initialTracksResolved || audioSelectionExplicit ? selectedAudioStreamIndex() : undefined,
                subtitleStreamIndex:
                    initialTracksResolved || subtitleSelectionExplicit
                        ? (selectedSubtitleTrack.value?.stream_index ?? -1)
                        : undefined,
                videoStreamIndex: selectedVideoTrack.value?.stream_index,
                playbackSessionId: playbackSessionId.value ?? undefined,
                playbackGeneration: playbackGeneration + 1,
                signal,
            },
        );
        signal.throwIfAborted();
        const source = response.MediaSources?.[0] as StreamSource | undefined;
        if (!source || source.PlayMethod === "None") throw new Error(t("player.noCompatibleMethod"));
        if (!initialTracksResolved) {
            // The server owns language aliases, fallback and forced/image-subtitle decisions.
            // Resolve once: subsequent transitions always send the user's current explicit choices.
            if (typeof source.AudioStreamIndex === "number") {
                selectedAudioTrack.value =
                    audioTracks.value.find((track) => track.stream_index === source.AudioStreamIndex) ||
                    selectedAudioTrack.value;
            }
            if ("SubtitleStreamIndex" in source) {
                selectedSubtitleTrack.value =
                    subtitleTracks.value.find((track) => track.stream_index === source.SubtitleStreamIndex) || null;
            }
            initialTracksResolved = true;
        }
        return source;
    }

    async function initializePlayback(resetRetries = true) {
        if (!props.mediaFile?.id) return;
        const position = hasSourceSet.value ? absolutePosition() : getResumePosition();
        if (resetRetries) retryCount.value = 0;
        await transitionPlayback(position, t("player.analyzing"), async (signal) => {
            const source = await requestPlaybackSource(signal);
            availableResolutions.value = (source.AvailableResolutions || []).map((r) => ({
                width: r.width as number,
                height: r.height as number,
                label: r.label as string,
                is_original: r.is_original as boolean,
            }));
            selectedResolution.value ??=
                availableResolutions.value.find((r) => r.is_original) || availableResolutions.value[0] || null;
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
        videoSrc.value = mediaSessionUrl(url, mediaAccess.value);
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
        mediaSourceRevision++;
        const sourceKey = sourceSettingsKey();
        const playbackKey = playbackSettingsKey();
        const previousJob = currentJobId.value;
        currentJobId.value = null;
        activePlaybackKey = null;
        hlsInstance.value?.destroy();
        hlsInstance.value = null;
        videoElement.value?.pause();
        clearExternalSubtitles();
        if (previousJob) {
            try {
                await media.stopHls(previousJob);
            } catch (error) {
                invalidateUnknownSession();
                throw error;
            }
        }
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
            if (!playbackSessionId.value) throw new Error("No active playback session");
            isHlsPlayback.value = true;
            const job = await startPlaybackJobService({
                mediaId: props.mediaFile.id,
                source,
                audioStreamIndex: selectedAudioStreamIndex(),
                subtitleStreamIndex: selectedBurnedSubtitleStreamIndex(),
                startTime: position,
                sessionId: playbackSessionId.value,
                signal,
                videoStreamIndex: selectedVideoTrack.value?.stream_index,
                playbackGeneration: ++playbackGeneration,
                onUnknownOutcome: invalidateUnknownSession,
            });
            currentJobId.value = job.id;
            try {
                const status = await waitForHlsReadyService(
                    job.id,
                    (status) => {
                        loadingMessage.value = t("player.transcodingProgress", {
                            progress: Math.round(status.progress_percent || 0),
                        });
                    },
                    120000,
                    signal,
                    mediaAccess.value,
                );
                signal.throwIfAborted();
                jobStartOffset.value = status.start_time ?? position;
                currentTime.value = Math.max(0, position - jobStartOffset.value);
                pendingInitialSeek.value = null;
                await setupHlsPlayer(media.getHlsPlaylistUrl(job.id, mediaAccess.value), currentTime.value, signal);
            } catch (error) {
                if (currentJobId.value === job.id) currentJobId.value = null;
                await media.stopHls(job.id).catch((error) => {
                    invalidateUnknownSession();
                    console.warn("Failed to stop HLS:", error);
                });
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
                    const parsed = new URL(url, window.location.origin);
                    if (parsed.origin === window.location.origin) {
                        xhr.open("GET", mediaSessionUrl(url, mediaAccess.value), true);
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
                    if (requestedPlaying.value)
                        videoElement.value.play().catch((e) => {
                            if (!isCurrent() || (e instanceof DOMException && e.name === "AbortError")) return;
                            requestedPlaying.value = false;
                            onControls();
                            console.warn("Autoplay blocked:", e);
                        });
                }
            });

            hls.on(Hls.Events.ERROR, (_event, data) => {
                if (!isCurrent()) return;
                console.error("HLS error:", data);

                // Log more details about audio buffer errors
                if (data.details?.includes("bufferAppend")) {
                    console.error("Buffer append error details:", {
                        sourceBufferName: data.sourceBufferName,
                        mediaSource: data.parent,
                        error: data.error,
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
                                    retryTimer = setTimeout(() => {
                                        if (isCurrent()) void initializePlayback(false);
                                    }, backoffDelay);
                                } else {
                                    console.error("Max retries reached, giving up");
                                    errorMessage.value = t("player.retry_failed");
                                    cleanup();
                                }
                            } else {
                                if (++networkRecoveries <= maxRetries) hls.startLoad();
                                else {
                                    errorMessage.value = t("player.retry_failed");
                                    cleanup();
                                }
                            }
                            break;
                        case Hls.ErrorTypes.MEDIA_ERROR:
                            if (++mediaRecoveries <= maxRetries) hls.recoverMediaError();
                            else {
                                errorMessage.value = t("player.retry_failed");
                                cleanup();
                            }
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
        mediaSourceRevision++;
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

    async function selectAudioTrack(track: AudioTrackOption) {
        audioSelectionExplicit = true;
        selectedAudioTrack.value = track;
        if (!isHlsPlayback.value && transitionPosition.value === null && selectNativeAudioTrack(track)) {
            activePlaybackKey = playbackSettingsKey();
            return;
        }
        const position = absolutePosition();
        await transitionPlayback(
            position,
            t("player.switchingAudio"),
            async (signal) => {
                // Re-negotiate the selected audio codec on the server. HLS is needed when
                // the browser cannot switch the direct file's AudioTrackList.
                const source = await requestPlaybackSource(signal, requestedResolution(), true);
                await replacePlayback(source, position, signal);
            },
            "player.audio_switch_failed",
        );
    }

    function selectNativeAudioTrack(track: AudioTrackOption): boolean {
        const video = videoElement.value as
            | (HTMLVideoElement & { audioTracks?: { length: number; [index: number]: { enabled: boolean } } })
            | null;
        const tracks = video?.audioTracks;
        // ffprobe indexes include video and subtitle streams; the browser list contains audio only.
        const index = audioTracks.value.findIndex(
            (candidate: AudioTrackOption) => candidate.stream_index === track.stream_index,
        );
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
        subtitleSelectionExplicit = true;
        selectedSubtitleTrack.value = track;
        clearExternalSubtitles();
        if (!initialTracksResolved || selectedBurnedSubtitleStreamIndex() !== appliedBurnedSubtitle) {
            const position = absolutePosition();
            await transitionPlayback(
                position,
                t("player.switchingSubtitles"),
                async (signal) => {
                    const source = await sourceForCurrentSelection(signal);
                    await replacePlayback(source, position, signal);
                },
                "player.subtitle_burn_failed",
            );
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
        const subtitleUrl = media.getSubtitleUrl(props.mediaFile.id, track.stream_index, mediaAccess.value);
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
                const blob = new Blob([adjustedVtt], { type: "text/vtt" });
                finalSubtitleUrl = URL.createObjectURL(blob);
                subtitleBlobUrls.value.push(finalSubtitleUrl);
            } catch (error) {
                if (request === subtitleRequest && !playbackAbort.signal.aborted)
                    console.warn("Failed to load subtitles:", error);
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
        await transitionPlayback(
            position,
            t("player.seeking_to", { time: formatTime(position) }),
            async (signal) => {
                const jobId = currentJobId.value;
                let status: TranscodingJob | undefined;
                if (jobId) {
                    try {
                        status = await media.getHlsStatus(jobId, signal);
                    } catch {
                        signal.throwIfAborted();
                    }
                }
                signal.throwIfAborted();
                const jobStart = status?.start_time ?? jobStartOffset.value;
                const jobEnd = jobStart + (status?.transcoded_duration ?? 0);
                if (
                    activePlaybackKey === playbackSettingsKey() &&
                    status &&
                    ["running", "completed"].includes(status.status) &&
                    position >= jobStart &&
                    position <= jobEnd - 2
                ) {
                    if (videoElement.value) videoElement.value.currentTime = position - jobStart;
                    currentTime.value = position - jobStart;
                    isLoading.value = false;
                } else {
                    const source = await sourceForCurrentSelection(signal);
                    await replacePlayback(source, position, signal);
                }
            },
            "player.seek_failed",
        );
    }

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
                const defaultAudio =
                    audioTracks.value.find((t: { is_default: boolean }) => t.is_default) || audioTracks.value[0];
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
            onControls();
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
            const absoluteStart = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + start : start;
            const absoluteEnd = isHlsPlayback.value ? (jobStartOffset.value ?? 0) + end : end;

            ranges.push({
                start: absoluteStart,
                end: absoluteEnd,
            });
        }

        bufferedRanges.value = ranges;
    }

    function togglePlay() {
        requestedPlaying.value = !requestedPlaying.value;
        if (!requestedPlaying.value) videoElement.value?.pause();
        else if (!isInitializing.value && !isLoading.value) {
            const revision = mediaSourceRevision;
            void videoElement.value?.play().catch((error) => {
                if (
                    revision !== mediaSourceRevision ||
                    playbackAbort.signal.aborted ||
                    (error instanceof DOMException && error.name === "AbortError")
                )
                    return;
                requestedPlaying.value = false;
            });
        }
        onControls();
    }

    function onPlay() {
        if (!requestedPlaying.value) {
            videoElement.value?.pause();
            return;
        }
        isPlaying.value = true;
        isLoading.value = false;
        sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
        // Show controls when play starts
        onControls();
    }

    function onPause() {
        isPlaying.value = false;
        if (!isInitializing.value && !isLoading.value) requestedPlaying.value = false;
        sendHeartbeat().catch((error) => console.warn("Playback heartbeat failed:", error));
        onControls();
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
        await transitionPlayback(
            position,
            t("player.transcodingFallback"),
            async (signal) => {
                await replacePlayback(
                    { PlayMethod: "Transcode", TranscodingType: "full", TranscodingUrl: "/start" },
                    position,
                    signal,
                );
            },
            "player.unsupported_format",
        );
    }

    function onCanPlay() {
        isLoading.value = false;
        if (resumeDirectPlayback) {
            resumeDirectPlayback = false;
            const revision = mediaSourceRevision;
            if (requestedPlaying.value)
                videoElement.value?.play().catch((error) => {
                    if (
                        revision !== mediaSourceRevision ||
                        playbackAbort.signal.aborted ||
                        (error instanceof DOMException && error.name === "AbortError")
                    )
                        return;
                    requestedPlaying.value = false;
                    onControls();
                    console.warn("Autoplay blocked:", error);
                });
        }
    }

    function onWaiting() {
        isLoading.value = true;
        loadingMessage.value = t("player.buffering");
    }

    function onPlaying() {
        isLoading.value = false;
        onControls();
    }

    async function selectResolution(resolution: {
        width: number;
        height: number;
        label: string;
        is_original: boolean;
    }) {
        if (selectedResolution.value === resolution) return;

        selectedResolution.value = resolution;

        if (resolution.is_original) {
            // Switch back to original resolution - restart with no resolution override
            await restartPlaybackWithResolution(null);
        } else {
            // Request specific resolution - force transcode
            await restartPlaybackWithResolution({
                width: resolution.width,
                height: resolution.height,
            });
        }
    }

    async function restartPlaybackWithResolution(resolution: { width: number; height: number } | null) {
        const position = absolutePosition();
        await transitionPlayback(
            position,
            t("player.switchingResolution"),
            async (signal) => {
                const source = await requestPlaybackSource(signal, resolution);
                await replacePlayback(source, position, signal);
            },
            "player.resolution_switch_failed",
        );
    }
    onUnmounted(() => {
        playbackAbort.abort();
        clearTimeout(retryTimer);
        stopHeartbeat();
        markPlaybackSessionEnded();
        cleanup();
    });
    return {
        canRetry,
        videoSrc,
        currentJobId,
        isPlaying: requestedPlaying,
        togglePlay,
        currentTime,
        duration,
        isLoading,
        loadingMessage,
        errorMessage,
        audioTracks,
        subtitleTracks,
        progressPercent,
        displayCurrentTime,
        bufferedPercentages,
        selectedResolutionLabel,
        playbackInfo,
        mediaInfo,
        codecInfo,
        transcodeReasons,
        selectedAudioTrack,
        selectedSubtitleTrack,
        selectedResolution,
        availableResolutions,
        isHlsPlayback,
        initializePlayback,
        applyInitialTrackSelection,
        selectAudioTrack,
        selectSubtitleTrack,
        selectResolution,
        seek,
        absolutePosition,
        onLoadedMetadata,
        onTimeUpdate,
        onProgress,
        onPlay,
        onPause,
        onError,
        onCanPlay,
        onWaiting,
        onPlaying,
    };
}
