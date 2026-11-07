/**
 * API client for Ferelix backend
 * Uses openapi-fetch for type-safe API calls with automatic token refresh
 */

import createClient, { type Middleware } from "openapi-fetch";
import { SESSION_EXPIRED_EVENT } from "@/services/authNavigation";
import type { components, paths } from "./types";

const TOKEN_KEY = "auth_access_token";
const REFRESH_KEY = "auth_refresh_token";
let tokenGeneration = 0;

// Re-export types from generated OpenAPI types
export type Library = components["schemas"]["LibrarySchema"];
export type LibraryCreate = components["schemas"]["LibraryCreate"];
export type LibraryUpdate = components["schemas"]["LibraryUpdate"];
export type MediaFile = components["schemas"]["MediaFileSchema"];
export type MediaCardInfo = components["schemas"]["MediaCardSchema"];
export type User = components["schemas"]["UserSchema"];
export type UserCreate = components["schemas"]["UserCreate"];
export type UserUpdate = components["schemas"]["UserUpdate"];
export type MediaView = components["schemas"]["MediaViewSchema"];
export type MediaViewUpdate = components["schemas"]["MediaViewUpdate"];
export type Job = components["schemas"]["JobSchema"];
export type JobExecution = components["schemas"]["JobExecutionSchema"];
export type ActiveStream = components["schemas"]["ActiveStreamSchema"];
export type RecommendationRow = components["schemas"]["RecommendationRowSchema"];
export type RecommendationRowCreate = components["schemas"]["RecommendationRowCreate"];
export type RecommendationRowUpdate = components["schemas"]["RecommendationRowUpdate"];
export type Settings = components["schemas"]["SettingsSchema"];
export type SettingsUpdate = components["schemas"]["SettingsUpdate"];
export type HardwareAccelerationStatus = components["schemas"]["HardwareAccelerationStatus"];
export type DirectoryItem = components["schemas"]["DirectoryItem"];
export type HomepageRow = components["schemas"]["HomepageRow"];
export type DeviceProfile = components["schemas"]["DeviceProfile"];
export type PlaybackInfoResponse = components["schemas"]["PlaybackInfoResponse"];
export type PlaybackSession = components["schemas"]["PlaybackSessionSchema"];
export type PlaybackSessionHeartbeatResponse = components["schemas"]["PlaybackSessionHeartbeatResponse"];
export type StreamInfo = components["schemas"]["StreamInfo"];
export type TranscodingJob = components["schemas"]["TranscodingJobSchema"];
export type LogLine = components["schemas"]["LogLineSchema"];
export type LogsResponse = components["schemas"]["LogsResponse"];
export type LogsConfig = components["schemas"]["LogsConfigResponse"];

export interface MediaAccess {
    sessionId: string;
    token: string;
}

/** Media URLs use a revocable playback grant, independent of short-lived API tokens. */
export function mediaSessionUrl(value: string, access?: MediaAccess): string {
    if (!access?.sessionId || !access.token) throw new Error("No active playback session");
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) throw new Error("Invalid media origin");
    url.searchParams.delete("api_key");
    url.searchParams.set("session_id", access.sessionId);
    url.searchParams.set("media_token", access.token);
    return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Get access token from localStorage
 */
export function getAccessToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
}

/**
 * Get refresh token from localStorage
 */
export function getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
}

/**
 * Save tokens to localStorage
 */
function persistTokens(accessToken: string, refreshToken: string): void {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_KEY, refreshToken);
}
export function saveTokens(accessToken: string, refreshToken: string): void {
    tokenGeneration++;
    persistTokens(accessToken, refreshToken);
}

/**
 * Clear tokens from localStorage
 */
export function clearTokens(): void {
    tokenGeneration++;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
    return !!getAccessToken();
}

function expireSession(): void {
    const wasAuthenticated = isAuthenticated();
    clearTokens();
    if (wasAuthenticated) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

let refreshPromise: Promise<string> | null = null;
const replayRequests = new WeakMap<Request, Request>();
const requestGenerations = new WeakMap<Request, number>();

function apiErrorMessage(error: unknown, fallback: string): string {
    if (error && typeof error === "object" && "detail" in error) {
        const detail = (error as { detail?: unknown }).detail;
        if (typeof detail === "string" && detail) {
            return detail;
        }
    }
    return fallback;
}

/**
 * Attempt to refresh the access token
 */
async function refreshAccessToken(): Promise<string> {
    const generation = tokenGeneration;
    const refreshToken = getRefreshToken();

    if (!refreshToken) {
        throw new Error("No refresh token available");
    }

    const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        signal: AbortSignal.timeout(12000),
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (generation !== tokenGeneration) throw new Error("Session changed during refresh");
    if (!response.ok) {
        if (response.status === 401 || response.status === 403) expireSession();
        throw new Error("Token refresh failed");
    }

    const data = await response.json();
    if (generation !== tokenGeneration) throw new Error("Session changed during refresh");
    persistTokens(data.access_token, data.refresh_token);
    return data.access_token;
}

/**
 * Auth middleware for openapi-fetch
 * Adds Authorization header and handles token refresh on 401
 */
const authMiddleware: Middleware = {
    async onRequest({ request }) {
        requestGenerations.set(request, tokenGeneration);
        const accessToken = getAccessToken();
        if (accessToken) {
            request.headers.set("Authorization", `Bearer ${accessToken}`);
        }
        // Clone before fetch consumes a JSON/FormData request body.
        replayRequests.set(request, request.clone());
        return request;
    },

    async onResponse({ request, response }) {
        const generation = requestGenerations.get(request);
        if (generation !== tokenGeneration) throw new Error("Session changed during request");
        if (response.status === 401 && getRefreshToken()) {
            refreshPromise ??= refreshAccessToken().finally(() => {
                refreshPromise = null;
            });
            // All waiting requests share both the success and failure of this refresh.
            const accessToken = await refreshPromise;
            if (generation !== tokenGeneration) throw new Error("Session changed during request");
            const retry = replayRequests.get(request);
            if (!retry) throw new Error("Request cannot be retried");
            retry.headers.set("Authorization", `Bearer ${accessToken}`);
            const retriedResponse = await fetch(retry);
            if (generation !== tokenGeneration) throw new Error("Session changed during request");
            if (retriedResponse.status === 401) expireSession();
            return retriedResponse;
        }
        if (response.status === 401) expireSession();
        return response;
    },
};

// Create the type-safe API client
const client = createClient<paths>({ baseUrl: "" });
client.use(authMiddleware);

// Also create a public client (no auth middleware) for login/setup endpoints
const publicClient = createClient<paths>({ baseUrl: "" });

// Export the raw client for direct access if needed
export { client, publicClient };

// Export authentication-related functions
export const auth = {
    /**
     * Login
     */
    async login(
        username: string,
        password: string,
        deviceInfo?: string | null,
    ): Promise<{ access_token: string; refresh_token: string; user?: User }> {
        const { data, error, response } = await publicClient.POST("/api/v1/auth/login", {
            signal: AbortSignal.timeout(15000),
            body: { username, password, device_info: deviceInfo },
        });

        if (error || !data) {
            throw Object.assign(new Error("Login failed"), { status: response.status });
        }

        saveTokens(data.access_token, data.refresh_token);
        return data as { access_token: string; refresh_token: string; user?: User };
    },

    /**
     * Logout
     */
    async logout(): Promise<void> {
        const refreshToken = getRefreshToken();
        const accessToken = getAccessToken();
        clearTokens();

        if (refreshToken) {
            try {
                await publicClient.POST("/api/v1/auth/logout", {
                    signal: AbortSignal.timeout(5000),
                    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
                    body: { refresh_token: refreshToken },
                });
            } catch (error) {
                console.error("Logout request failed:", error);
            }
        }
    },

    /**
     * Check setup status
     */
    async checkSetupStatus(): Promise<{ setup_complete: boolean } | null> {
        const { data } = await publicClient.GET("/api/v1/setup/status");
        return (data as { setup_complete: boolean }) ?? null;
    },

    /**
     * Create admin account (first-time setup)
     */
    async createAdmin(
        username: string,
        password: string,
        language = "en",
    ): Promise<{ access_token: string; refresh_token: string } | null> {
        const { data, error } = await publicClient.POST("/api/v1/setup/admin", {
            body: { username, password, language },
        });

        if (error || !data) throw new Error(apiErrorMessage(error, "Setup failed"));
        if (data.access_token && data.refresh_token) {
            saveTokens(data.access_token, data.refresh_token);
        }

        return data ?? null;
    },

    /**
     * Get current user information
     */
    async getCurrentUser(): Promise<User> {
        const { data, error } = await client.GET("/api/v1/users/me", { signal: AbortSignal.timeout(15000) });
        if (error || !data) {
            throw new Error("Failed to get current user");
        }
        return data;
    },

    /**
     * Update current user information
     */
    async updateCurrentUser(userData: UserUpdate): Promise<User> {
        const { data, error } = await client.PATCH("/api/v1/users/me", {
            body: userData,
        });
        if (error || !data) {
            throw new Error(apiErrorMessage(error, "Failed to update current user"));
        }
        return data;
    },

    /**
     * Upload current user's cropped profile image
     */
    async uploadCurrentUserProfileImage(image: File): Promise<User> {
        const formData = new FormData();
        formData.append("image", image);
        const accessToken = getAccessToken();
        const response = await fetch("/api/v1/users/me/profile-image", {
            method: "PUT",
            headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
            body: formData,
        });
        if (!response.ok) {
            throw new Error("Failed to upload profile image");
        }
        return (await response.json()) as User;
    },

    /**
     * Delete current user's profile image
     */
    async deleteCurrentUserProfileImage(): Promise<User> {
        const accessToken = getAccessToken();
        const response = await fetch("/api/v1/users/me/profile-image", {
            method: "DELETE",
            headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
        });
        if (!response.ok) {
            throw new Error("Failed to delete profile image");
        }
        return (await response.json()) as User;
    },
};

export const watchlist = {
    async list(skip = 0, limit = 49, signal?: AbortSignal): Promise<MediaCardInfo[]> {
        const { data, error } = await client.GET("/api/v1/users/me/watchlist", {
            signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
            params: { query: { skip, limit } },
        });
        if (error || !data) throw new Error("Failed to get watchlist");
        return data;
    },
    async add(mediaId: number) {
        const { data, error } = await client.PUT("/api/v1/users/me/watchlist/{media_id}", {
            signal: AbortSignal.timeout(15000),
            params: { path: { media_id: mediaId } },
        });
        if (error || !data) throw new Error("Failed to add to watchlist");
        return data;
    },
    async remove(mediaId: number) {
        const { data, error } = await client.DELETE("/api/v1/users/me/watchlist/{media_id}", {
            signal: AbortSignal.timeout(15000),
            params: { path: { media_id: mediaId } },
        });
        if (error || !data) throw new Error("Failed to remove from watchlist");
        return data;
    },
};

// Export media-related functions
export const media = {
    async search(q: string, skip = 0, limit = 49, signal?: AbortSignal): Promise<MediaCardInfo[]> {
        const { data, error } = await client.GET("/api/v1/media-files/search", {
            signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
            params: { query: { q, skip, limit, sort: "relevance" } },
        });
        if (error || !data) throw new Error("Failed to search media");
        return data;
    },
    /**
     * Get media files the current user started but has not finished
     */
    async getContinueWatching(limit = 24): Promise<MediaCardInfo[]> {
        const { data, error } = await client.GET("/api/v1/media-files/continue-watching", {
            params: { query: { limit } },
        });
        if (error || !data) {
            throw new Error("Failed to get continue watching media");
        }
        return data;
    },

    /**
     * Get media file by ID
     */
    async getMediaFile(id: number): Promise<MediaFile> {
        const { data, error } = await client.GET("/api/v1/media/{media_id}", {
            params: { path: { media_id: id } },
        });
        if (error || !data) {
            throw new Error("Failed to get media file");
        }
        return data;
    },

    /**
     * Get playback info for a media file
     * Returns recommended playback method (DirectPlay, DirectStream, Transcode)
     */
    async getPlaybackInfo(
        mediaId: number,
        deviceProfile: components["schemas"]["DeviceProfile"],
        options?: {
            enableDirectPlay?: boolean;
            enableDirectStream?: boolean;
            enableTranscoding?: boolean;
            requestedResolution?: { width: number; height: number } | null;
            audioStreamIndex?: number;
            subtitleStreamIndex?: number;
            videoStreamIndex?: number;
            playbackSessionId?: string;
            playbackGeneration?: number;
            signal?: AbortSignal;
        },
    ): Promise<components["schemas"]["PlaybackInfoResponse"]> {
        const { data, error } = await client.POST("/api/v1/playback-info/{media_id}", {
            signal: options?.signal,
            params: { path: { media_id: mediaId } },
            body: {
                DeviceProfile: deviceProfile,
                EnableDirectPlay: options?.enableDirectPlay ?? true,
                EnableDirectStream: options?.enableDirectStream ?? true,
                EnableTranscoding: options?.enableTranscoding ?? true,
                AllowVideoStreamCopy: true,
                AllowAudioStreamCopy: true,
                IsPlayback: true,
                RequestedResolution: options?.requestedResolution,
                AudioStreamIndex: options?.audioStreamIndex,
                SubtitleStreamIndex: options?.subtitleStreamIndex,
                VideoStreamIndex: options?.videoStreamIndex,
                PlaybackSessionId: options?.playbackSessionId,
                PlaybackGeneration: options?.playbackGeneration ?? 1,
            },
        });
        if (error || !data) {
            throw new Error("Failed to get playback info");
        }
        return data;
    },

    /**
     * Start HLS remux (container conversion only, fast)
     */
    async startRemux(
        mediaId: number,
        options: {
            audioStreamIndex?: number;
            startTime?: number;
            sessionId: string;
            playbackGeneration: number;
            videoStreamIndex?: number;
            signal?: AbortSignal;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error, response } = await client.POST("/api/v1/hls/{media_id}/remux", {
            signal: options.signal,
            params: {
                path: { media_id: mediaId },
                query: {
                    audio_stream_index: options?.audioStreamIndex,
                    start_time: options?.startTime,
                    session_id: options.sessionId,
                    playback_generation: options.playbackGeneration,
                    video_stream_index: options.videoStreamIndex,
                },
            },
        });
        if (error || !data) {
            throw Object.assign(new Error(apiErrorMessage(error, "Failed to start remux")), {
                status: response.status,
            });
        }
        return data;
    },

    /**
     * Start HLS transcoding
     */
    async startTranscode(
        mediaId: number,
        options: {
            videoCodec?: string;
            audioCodec?: string;
            videoBitrate?: number;
            audioBitrate?: number;
            maxWidth?: number;
            maxHeight?: number;
            maxFrameRate?: number;
            audioStreamIndex?: number;
            subtitleStreamIndex?: number;
            startTime?: number;
            sessionId: string;
            playbackGeneration: number;
            videoStreamIndex?: number;
            signal?: AbortSignal;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error, response } = await client.POST("/api/v1/hls/{media_id}/start", {
            signal: options.signal,
            params: {
                path: { media_id: mediaId },
                query: {
                    video_codec: options?.videoCodec ?? "h264",
                    audio_codec: options?.audioCodec ?? "aac",
                    video_bitrate: options?.videoBitrate,
                    audio_bitrate: options?.audioBitrate,
                    max_width: options?.maxWidth,
                    max_height: options?.maxHeight,
                    max_frame_rate: options?.maxFrameRate,
                    audio_stream_index: options?.audioStreamIndex,
                    subtitle_stream_index: options?.subtitleStreamIndex,
                    start_time: options?.startTime,
                    session_id: options.sessionId,
                    playback_generation: options.playbackGeneration,
                    video_stream_index: options.videoStreamIndex,
                },
            },
        });
        if (error || !data) {
            throw Object.assign(new Error(apiErrorMessage(error, "Failed to start transcode")), {
                status: response.status,
            });
        }
        return data;
    },

    /**
     * Start HLS audio-only transcode (video copy)
     */
    async startAudioTranscode(
        mediaId: number,
        options: {
            audioCodec?: string;
            audioBitrate?: number;
            audioStreamIndex?: number;
            startTime?: number;
            sessionId: string;
            playbackGeneration: number;
            videoStreamIndex?: number;
            signal?: AbortSignal;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error, response } = await client.POST("/api/v1/hls/{media_id}/audio-transcode", {
            signal: options.signal,
            params: {
                path: { media_id: mediaId },
                query: {
                    audio_codec: options?.audioCodec ?? "aac",
                    audio_bitrate: options?.audioBitrate ?? 128000,
                    audio_stream_index: options?.audioStreamIndex,
                    start_time: options?.startTime,
                    session_id: options.sessionId,
                    playback_generation: options.playbackGeneration,
                    video_stream_index: options.videoStreamIndex,
                },
            },
        });
        if (error || !data) {
            throw Object.assign(new Error(apiErrorMessage(error, "Failed to start audio transcode")), {
                status: response.status,
            });
        }
        return data;
    },

    /**
     * Get HLS job status
     */
    async getHlsStatus(jobId: string, signal?: AbortSignal): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error } = await client.GET("/api/v1/hls/{job_id}/status", {
            signal,
            params: { path: { job_id: jobId } },
        });
        if (error || !data) {
            throw new Error("Failed to get HLS status");
        }
        return data;
    },

    /**
     * Stop HLS transcoding job
     */
    async stopHls(jobId: string): Promise<void> {
        const { error } = await client.DELETE("/api/v1/hls/{job_id}/stop", {
            signal: AbortSignal.timeout(10000),
            params: { path: { job_id: jobId } },
        });
        if (error) {
            throw new Error("Failed to stop HLS job");
        }
    },

    /**
     * Get subtitle URL for external WebVTT
     */
    getSubtitleUrl(mediaId: number, streamIndex: number, access?: MediaAccess): string {
        return mediaSessionUrl(`/api/v1/subtitle/${mediaId}/${streamIndex}`, access);
    },

    getDirectStreamUrl(mediaId: number, access?: MediaAccess): string {
        return mediaSessionUrl(`/api/v1/stream/${mediaId}`, access);
    },

    /**
     * Get generated thumbnail URL
     */
    getThumbnailUrl(mediaId: number): string {
        const token = getAccessToken();
        const baseUrl = `/api/v1/media/${mediaId}/thumbnail`;
        return token ? `${baseUrl}?api_key=${token}` : baseUrl;
    },

    /**
     * Get HLS playlist URL
     */
    getHlsPlaylistUrl(jobId: string, access?: MediaAccess): string {
        return mediaSessionUrl(`/api/v1/hls/${jobId}/playlist.m3u8`, access);
    },
};

// Export library-related functions
export const libraries = {
    /**
     * Get all enabled libraries (for authenticated users)
     */
    async getLibraries(): Promise<Library[]> {
        const { data, error } = await client.GET("/api/v1/libraries");
        if (error || !data) {
            throw new Error("Failed to get libraries");
        }
        return data;
    },

    /**
     * Get items from a specific library
     */
    async getLibraryItems(libraryId: number, skip = 0, limit = 48, signal?: AbortSignal): Promise<MediaCardInfo[]> {
        const { data, error } = await client.GET("/api/v1/libraries/{library_id}/items", {
            signal,
            params: {
                path: { library_id: libraryId },
                query: { skip, limit },
            },
        });
        if (error || !data) {
            throw new Error("Failed to get library items");
        }
        return data;
    },

    /**
     * Get all libraries (admin only - for management)
     */
    async getAllLibraries(): Promise<Library[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/libraries");
        if (error || !data) {
            throw new Error("Failed to get all libraries");
        }
        return data;
    },

    /**
     * Create a new library
     */
    async createLibrary(
        name: string,
        path: string,
        libraryType: "movie" | "show" = "movie",
        enabled = true,
    ): Promise<Library> {
        const { data, error } = await client.POST("/api/v1/dashboard/libraries", {
            body: {
                name,
                path,
                library_type: libraryType,
                enabled,
            },
        });
        if (error || !data) {
            throw new Error("Failed to create library");
        }
        return data;
    },

    /**
     * Update a library
     */
    async updateLibrary(id: number, libraryData: LibraryUpdate): Promise<Library> {
        const { data, error } = await client.PATCH("/api/v1/dashboard/libraries/{library_id}", {
            params: { path: { library_id: id } },
            body: libraryData,
        });
        if (error || !data) {
            throw new Error("Failed to update library");
        }
        return data;
    },

    /**
     * Delete a library
     */
    async deleteLibrary(id: number): Promise<void> {
        const { error } = await client.DELETE("/api/v1/dashboard/libraries/{library_id}", {
            params: { path: { library_id: id } },
        });
        if (error) {
            throw new Error("Failed to delete library");
        }
    },

    /**
     * Trigger a scan for a specific library (admin only)
     */
    async scanLibrary(libraryId: number): Promise<void> {
        const { error } = await client.POST("/api/v1/dashboard/libraries/{library_id}/scan", {
            params: { path: { library_id: libraryId } },
        });
        if (error) {
            throw new Error("Failed to scan library");
        }
    },

    /**
     * Browse directories at a given path (admin only)
     */
    async browseDirectory(path: string): Promise<DirectoryItem[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/browse", {
            params: { query: { path } },
        });
        if (error || !data) {
            throw new Error("Failed to browse directory");
        }
        return data;
    },

    /**
     * Get homepage rows
     */
    async getHomepageRows(): Promise<HomepageRow[]> {
        const { data, error } = await client.GET("/api/v1/homepage/rows");
        if (error || !data) {
            throw new Error("Failed to get homepage rows");
        }
        return data;
    },

    /**
     * Get rows for a specific library
     */
    async getLibraryRows(libraryId: number, signal?: AbortSignal): Promise<HomepageRow[]> {
        const { data, error } = await client.GET("/api/v1/libraries/{library_id}/rows", {
            signal,
            params: { path: { library_id: libraryId } },
        });
        if (error || !data) {
            throw new Error("Failed to get library rows");
        }
        return data;
    },
};

// Export job-related functions
export const jobs = {
    /**
     * Get all scheduled jobs (admin only)
     */
    async getJobs(): Promise<Job[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/jobs");
        if (error || !data) {
            throw new Error("Failed to get jobs");
        }
        return data;
    },

    /**
     * Get job execution history (admin only)
     */
    async getJobHistory(): Promise<JobExecution[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/jobs/history");
        if (error || !data) {
            throw new Error("Failed to get job history");
        }
        return data;
    },

    /**
     * Trigger a job manually (admin only)
     */
    async triggerJob(jobId: string): Promise<void> {
        const { error } = await client.POST("/api/v1/dashboard/jobs/{job_id}/trigger", {
            params: { path: { job_id: jobId } },
        });
        if (error) {
            throw new Error("Failed to trigger job");
        }
    },

    /**
     * Cancel a running job (admin only)
     */
    async cancelJob(jobId: string): Promise<void> {
        const { error } = await client.POST("/api/v1/dashboard/jobs/{job_id}/cancel", {
            params: { path: { job_id: jobId } },
        });
        if (error) {
            throw new Error("Failed to cancel job");
        }
    },
};

// Export active stream-related functions
export const streams = {
    /**
     * Get active playback/transcoding streams across all users (admin only)
     */
    async getActiveStreams(): Promise<ActiveStream[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/streams");
        if (error || !data) {
            throw new Error("Failed to get active streams");
        }
        return data;
    },

    /**
     * Stop an active HLS/remux/transcoding stream
     */
    async stopStream(jobId: string): Promise<void> {
        const { error } = await client.DELETE("/api/v1/dashboard/streams/{session_id}", {
            params: { path: { session_id: jobId } },
        });
        if (error) {
            throw new Error("Failed to stop stream");
        }
    },
};

export const serverLogs = {
    async getConfig(): Promise<LogsConfig> {
        const { data, error } = await client.GET("/api/v1/dashboard/logs/config");
        if (error || !data) {
            throw new Error("Failed to get server logs configuration");
        }
        return data;
    },

    async getLogs(options?: {
        maxLines?: number;
        allLines?: boolean;
        levels?: string[];
        channels?: string[];
    }): Promise<LogsResponse> {
        const { data, error } = await client.GET("/api/v1/dashboard/logs", {
            params: {
                query: {
                    max_lines: options?.maxLines ?? 1000,
                    all_lines: options?.allLines ?? false,
                    levels: options?.levels,
                    channels: options?.channels,
                },
            },
        });
        if (error || !data) {
            throw new Error("Failed to get server logs");
        }
        return data;
    },

    async tail(offset: number, options?: { levels?: string[]; channels?: string[] }): Promise<LogsResponse> {
        const { data, error } = await client.GET("/api/v1/dashboard/logs/tail", {
            params: { query: { offset, levels: options?.levels, channels: options?.channels } },
        });
        if (error || !data) {
            throw new Error("Failed to tail server logs");
        }
        return data;
    },
};

// Export admin user-management functions
export const dashboardUsers = {
    async listUsers(): Promise<User[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/users");
        if (error || !data) {
            throw new Error("Failed to get users");
        }
        return data;
    },

    async createUser(userData: UserCreate): Promise<User> {
        const { data, error } = await client.POST("/api/v1/dashboard/users", {
            body: userData,
        });
        if (error || !data) {
            throw new Error("Failed to create user");
        }
        return data;
    },

    async updateUser(id: number, userData: UserUpdate): Promise<User> {
        const { data, error } = await client.PATCH("/api/v1/dashboard/users/{user_id}", {
            params: { path: { user_id: id } },
            body: userData,
        });
        if (error || !data) {
            throw new Error("Failed to update user");
        }
        return data;
    },

    async deleteUser(id: number): Promise<void> {
        const { error } = await client.DELETE("/api/v1/dashboard/users/{user_id}", {
            params: { path: { user_id: id } },
        });
        if (error) {
            throw new Error("Failed to delete user");
        }
    },

    async uploadProfileImage(id: number, image: File): Promise<User> {
        const formData = new FormData();
        formData.append("image", image);
        const accessToken = getAccessToken();
        const response = await fetch(`/api/v1/dashboard/users/${id}/profile-image`, {
            method: "PUT",
            headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
            body: formData,
        });
        if (!response.ok) {
            throw new Error("Failed to upload profile image");
        }
        return (await response.json()) as User;
    },

    async deleteProfileImage(id: number): Promise<User> {
        const { data, error } = await client.DELETE("/api/v1/dashboard/users/{user_id}/profile-image", {
            params: { path: { user_id: id } },
        });
        if (error || !data) {
            throw new Error("Failed to delete profile image");
        }
        return data;
    },
};

// Export playback session-related functions
export const playbackSessions = {
    async create(
        payload: {
            mediaFileId: number;
            durationSeconds?: number | null;
            audioStreamIndex?: number | null;
            videoStreamIndex?: number | null;
            subtitleStreamIndex?: number | null;
        },
        signal?: AbortSignal,
    ): Promise<PlaybackSession> {
        const { data, error } = await client.POST("/api/v1/playback-sessions", {
            signal,
            body: {
                media_file_id: payload.mediaFileId,
                duration_seconds: payload.durationSeconds,
                audio_stream_index: payload.audioStreamIndex,
                video_stream_index: payload.videoStreamIndex,
                subtitle_stream_index: payload.subtitleStreamIndex,
            },
        });
        if (error || !data) {
            throw new Error("Failed to create playback session");
        }
        return data;
    },

    async heartbeat(
        sessionId: string,
        payload: {
            positionSeconds: number;
            playbackGeneration: number;
            durationSeconds?: number | null;
            isPaused: boolean;
            playMethod?: string | null;
            transcodingType?: string | null;
            transcodingJobId?: string | null;
            audioStreamIndex?: number | null;
            videoStreamIndex?: number | null;
            subtitleStreamIndex?: number | null;
        },
    ): Promise<PlaybackSessionHeartbeatResponse> {
        const { data, error } = await client.POST("/api/v1/playback-sessions/{session_id}/heartbeat", {
            params: { path: { session_id: sessionId } },
            body: {
                position_seconds: payload.positionSeconds,
                playback_generation: payload.playbackGeneration,
                duration_seconds: payload.durationSeconds,
                is_paused: payload.isPaused,
                play_method: payload.playMethod,
                transcoding_type: payload.transcodingType,
                transcoding_job_id: payload.transcodingJobId,
                audio_stream_index: payload.audioStreamIndex,
                video_stream_index: payload.videoStreamIndex,
                subtitle_stream_index: payload.subtitleStreamIndex,
            },
        });
        if (error || !data) {
            throw new Error("Failed to update playback session");
        }
        return data;
    },

    async end(sessionId: string, signal?: AbortSignal): Promise<void> {
        const { error } = await client.DELETE("/api/v1/playback-sessions/{session_id}", {
            signal,
            params: { path: { session_id: sessionId } },
        });
        if (error) {
            throw new Error("Failed to end playback session");
        }
    },
};

// Export settings-related functions
export const settings = {
    /**
     * Get application settings (admin only)
     */
    async getSettings(): Promise<Settings> {
        const { data, error } = await client.GET("/api/v1/dashboard/settings");
        if (error || !data) {
            throw new Error("Failed to get settings");
        }
        return data;
    },

    /**
     * Update application settings (admin only)
     */
    async updateSettings(settingsData: SettingsUpdate): Promise<Settings> {
        const { data, error } = await client.PATCH("/api/v1/dashboard/settings", {
            body: settingsData,
        });
        if (error || !data) {
            throw new Error("Failed to update settings");
        }
        return data;
    },

    /**
     * Get detected hardware transcoding devices (admin only)
     */
    async getHardwareTranscodingStatus(refresh = false): Promise<HardwareAccelerationStatus> {
        const { data, error } = await client.GET("/api/v1/dashboard/hardware-transcoding", {
            params: { query: { refresh } },
        });
        if (error || !data) {
            throw new Error("Failed to get hardware transcoding status");
        }
        return data;
    },
};

// Export recommendation row-related functions
export const recommendationRows = {
    /**
     * Get all recommendation rows (admin only)
     */
    async getRows(skip = 0, limit = 100): Promise<RecommendationRow[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/recommendation-rows", {
            params: { query: { skip, limit } },
        });
        if (error || !data) {
            throw new Error("Failed to get recommendation rows");
        }
        return data;
    },

    /**
     * Get recommendation row by ID (admin only)
     */
    async getRow(id: number): Promise<RecommendationRow> {
        const { data, error } = await client.GET("/api/v1/dashboard/recommendation-rows/{row_id}", {
            params: { path: { row_id: id } },
        });
        if (error || !data) {
            throw new Error("Failed to get recommendation row");
        }
        return data;
    },

    /**
     * Create a new recommendation row (admin only)
     */
    async createRow(rowData: RecommendationRowCreate): Promise<RecommendationRow> {
        const { data, error } = await client.POST("/api/v1/dashboard/recommendation-rows", {
            body: rowData,
        });
        if (error || !data) {
            throw new Error("Failed to create recommendation row");
        }
        return data;
    },

    /**
     * Update a recommendation row (admin only)
     */
    async updateRow(id: number, rowData: RecommendationRowUpdate): Promise<RecommendationRow> {
        const { data, error } = await client.PATCH("/api/v1/dashboard/recommendation-rows/{row_id}", {
            params: { path: { row_id: id } },
            body: rowData,
        });
        if (error || !data) {
            throw new Error("Failed to update recommendation row");
        }
        return data;
    },

    /**
     * Delete a recommendation row (admin only)
     */
    async deleteRow(id: number): Promise<void> {
        const { error } = await client.DELETE("/api/v1/dashboard/recommendation-rows/{row_id}", {
            params: { path: { row_id: id } },
        });
        if (error) {
            throw new Error("Failed to delete recommendation row");
        }
    },

    /**
     * Get recommendation rows for a library (admin only)
     */
    async getLibraryRows(libraryId: number): Promise<RecommendationRow[]> {
        const { data, error } = await client.GET("/api/v1/dashboard/libraries/{library_id}/recommendation-rows", {
            params: { path: { library_id: libraryId } },
        });
        if (error || !data) {
            throw new Error("Failed to get library recommendation rows");
        }
        return data;
    },

    /**
     * Add a recommendation row to a library (admin only)
     */
    async addLibraryRow(libraryId: number, rowData: RecommendationRowCreate): Promise<RecommendationRow> {
        const { data, error } = await client.POST("/api/v1/dashboard/libraries/{library_id}/recommendation-rows", {
            params: { path: { library_id: libraryId } },
            body: rowData,
        });
        if (error || !data) {
            throw new Error("Failed to add library recommendation row");
        }
        return data;
    },

    /**
     * Update a recommendation row's visibility for a library (admin only)
     */
    async updateLibraryRow(
        libraryId: number,
        rowId: number,
        rowData: RecommendationRowUpdate,
    ): Promise<RecommendationRow> {
        const { data, error } = await client.PATCH(
            "/api/v1/dashboard/libraries/{library_id}/recommendation-rows/{row_id}",
            {
                params: { path: { library_id: libraryId, row_id: rowId } },
                body: rowData,
            },
        );
        if (error || !data) {
            throw new Error("Failed to update library recommendation row");
        }
        return data;
    },

    /**
     * Remove a recommendation row from a library (admin only)
     */
    async removeLibraryRow(libraryId: number, rowId: number): Promise<void> {
        const { error } = await client.DELETE("/api/v1/dashboard/libraries/{library_id}/recommendation-rows/{row_id}", {
            params: { path: { library_id: libraryId, row_id: rowId } },
        });
        if (error) {
            throw new Error("Failed to remove library recommendation row");
        }
    },
};
