/**
 * API client for Ferelix backend
 * Uses openapi-fetch for type-safe API calls with automatic token refresh
 */

import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./types";

const TOKEN_KEY = "auth_access_token";
const REFRESH_KEY = "auth_refresh_token";

// Re-export types from generated OpenAPI types
export type Library = components["schemas"]["LibrarySchema"];
export type LibraryCreate = components["schemas"]["LibraryCreate"];
export type LibraryUpdate = components["schemas"]["LibraryUpdate"];
export type MediaFile = components["schemas"]["MediaFileSchema"];
export type User = components["schemas"]["UserSchema"];
export type UserUpdate = components["schemas"]["UserUpdate"];
export type Job = components["schemas"]["JobSchema"];
export type JobExecution = components["schemas"]["JobExecutionSchema"];
export type RecommendationRow = components["schemas"]["RecommendationRowSchema"];
export type RecommendationRowCreate = components["schemas"]["RecommendationRowCreate"];
export type RecommendationRowUpdate = components["schemas"]["RecommendationRowUpdate"];
export type Settings = components["schemas"]["SettingsSchema"];
export type SettingsUpdate = components["schemas"]["SettingsUpdate"];
export type DirectoryItem = components["schemas"]["DirectoryItem"];
export type HomepageRow = components["schemas"]["HomepageRow"];
export type DeviceProfile = components["schemas"]["DeviceProfile"];
export type PlaybackInfoResponse = components["schemas"]["PlaybackInfoResponse"];
export type StreamInfo = components["schemas"]["StreamInfo"];
export type TranscodingJob = components["schemas"]["TranscodingJobSchema"];

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
export function saveTokens(accessToken: string, refreshToken: string): void {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_KEY, refreshToken);
}

/**
 * Clear tokens from localStorage
 */
export function clearTokens(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
    return !!getAccessToken();
}

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

/**
 * Subscribe to token refresh completion
 */
function subscribeTokenRefresh(callback: (token: string) => void): void {
    refreshSubscribers.push(callback);
}

/**
 * Notify all subscribers when token refresh completes
 */
function onTokenRefreshed(accessToken: string): void {
    for (const callback of refreshSubscribers) {
        callback(accessToken);
    }
    refreshSubscribers = [];
}

/**
 * Attempt to refresh the access token
 */
async function refreshAccessToken(): Promise<string> {
    const refreshToken = getRefreshToken();

    if (!refreshToken) {
        throw new Error("No refresh token available");
    }

    const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
        clearTokens();
        window.location.href = "/login";
        throw new Error("Token refresh failed");
    }

    const data = await response.json();
    saveTokens(data.access_token, data.refresh_token);
    return data.access_token;
}

/**
 * Auth middleware for openapi-fetch
 * Adds Authorization header and handles token refresh on 401
 */
const authMiddleware: Middleware = {
    async onRequest({ request }) {
        const accessToken = getAccessToken();
        if (accessToken) {
            request.headers.set("Authorization", `Bearer ${accessToken}`);
        }
        return request;
    },

    async onResponse({ request, response }) {
        if (response.status === 401 && getRefreshToken()) {
            if (!isRefreshing) {
                isRefreshing = true;

                try {
                    const newAccessToken = await refreshAccessToken();
                    isRefreshing = false;
                    onTokenRefreshed(newAccessToken);

                    // Retry original request with new token
                    const newRequest = request.clone();
                    newRequest.headers.set("Authorization", `Bearer ${newAccessToken}`);
                    return fetch(newRequest);
                } catch (error) {
                    isRefreshing = false;
                    throw error;
                }
            } else {
                // Wait for ongoing refresh to complete
                const newAccessToken = await new Promise<string>((resolve) => {
                    subscribeTokenRefresh(resolve);
                });

                // Retry with new token
                const newRequest = request.clone();
                newRequest.headers.set("Authorization", `Bearer ${newAccessToken}`);
                return fetch(newRequest);
            }
        }

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
        const { data, error } = await publicClient.POST("/api/v1/auth/login", {
            body: { username, password, device_info: deviceInfo },
        });

        if (error || !data) {
            throw new Error("Login failed");
        }

        saveTokens(data.access_token, data.refresh_token);
        return data as { access_token: string; refresh_token: string; user?: User };
    },

    /**
     * Logout
     */
    async logout(): Promise<void> {
        const refreshToken = getRefreshToken();

        if (refreshToken) {
            try {
                await client.POST("/api/v1/auth/logout", {
                    body: { refresh_token: refreshToken },
                });
            } catch (error) {
                console.error("Logout request failed:", error);
            }
        }

        clearTokens();
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
        const { data } = await publicClient.POST("/api/v1/setup/admin", {
            body: { username, password, language },
        });

        if (data?.access_token && data?.refresh_token) {
            saveTokens(data.access_token, data.refresh_token);
        }

        return data ?? null;
    },

    /**
     * Get current user information
     */
    async getCurrentUser(): Promise<User> {
        const { data, error } = await client.GET("/api/v1/users/me");
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
            throw new Error("Failed to update current user");
        }
        return data;
    },
};

// Export media-related functions
export const media = {
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
        },
    ): Promise<components["schemas"]["PlaybackInfoResponse"]> {
        const { data, error } = await client.POST("/api/v1/playback-info/{media_id}", {
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
        options?: {
            audioStreamIndex?: number;
            startTime?: number;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error } = await client.POST("/api/v1/hls/{media_id}/remux", {
            params: {
                path: { media_id: mediaId },
                query: {
                    audio_stream_index: options?.audioStreamIndex,
                    start_time: options?.startTime,
                },
            },
        });
        if (error || !data) {
            throw new Error("Failed to start remux");
        }
        return data;
    },

    /**
     * Start HLS transcoding
     */
    async startTranscode(
        mediaId: number,
        options?: {
            videoCodec?: string;
            audioCodec?: string;
            videoBitrate?: number;
            audioBitrate?: number;
            maxWidth?: number;
            maxHeight?: number;
            audioStreamIndex?: number;
            subtitleStreamIndex?: number;
            startTime?: number;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error } = await client.POST("/api/v1/hls/{media_id}/start", {
            params: {
                path: { media_id: mediaId },
                query: {
                    video_codec: options?.videoCodec ?? "h264",
                    audio_codec: options?.audioCodec ?? "aac",
                    video_bitrate: options?.videoBitrate,
                    audio_bitrate: options?.audioBitrate,
                    max_width: options?.maxWidth,
                    max_height: options?.maxHeight,
                    audio_stream_index: options?.audioStreamIndex,
                    subtitle_stream_index: options?.subtitleStreamIndex,
                    start_time: options?.startTime,
                },
            },
        });
        if (error || !data) {
            throw new Error("Failed to start transcode");
        }
        return data;
    },

    /**
     * Start HLS audio-only transcode (video copy)
     */
    async startAudioTranscode(
        mediaId: number,
        options?: {
            audioCodec?: string;
            audioBitrate?: number;
            audioStreamIndex?: number;
            startTime?: number;
        },
    ): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error } = await client.POST("/api/v1/hls/{media_id}/audio-transcode", {
            params: {
                path: { media_id: mediaId },
                query: {
                    audio_codec: options?.audioCodec ?? "aac",
                    audio_bitrate: options?.audioBitrate ?? 128000,
                    audio_stream_index: options?.audioStreamIndex,
                    start_time: options?.startTime,
                },
            },
        });
        if (error || !data) {
            throw new Error("Failed to start audio transcode");
        }
        return data;
    },

    /**
     * Get HLS job status
     */
    async getHlsStatus(jobId: string): Promise<components["schemas"]["TranscodingJobSchema"]> {
        const { data, error } = await client.GET("/api/v1/hls/{job_id}/status", {
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
            params: { path: { job_id: jobId } },
        });
        if (error) {
            throw new Error("Failed to stop HLS job");
        }
    },

    /**
     * Get subtitle URL for external WebVTT
     */
    getSubtitleUrl(mediaId: number, streamIndex: number): string {
        const token = getAccessToken();
        const baseUrl = `/api/v1/subtitle/${mediaId}/${streamIndex}`;
        return token ? `${baseUrl}?api_key=${token}` : baseUrl;
    },

    /**
     * Get direct stream URL
     */
    getDirectStreamUrl(mediaId: number): string {
        const token = getAccessToken();
        const baseUrl = `/api/v1/stream/${mediaId}`;
        return token ? `${baseUrl}?api_key=${token}` : baseUrl;
    },

    /**
     * Get HLS playlist URL
     */
    getHlsPlaylistUrl(jobId: string): string {
        const token = getAccessToken();
        const baseUrl = `/api/v1/hls/${jobId}/playlist.m3u8`;
        return token ? `${baseUrl}?api_key=${token}` : baseUrl;
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
    async getLibraryItems(libraryId: number, skip = 0, limit = 100): Promise<MediaFile[]> {
        const { data, error } = await client.GET("/api/v1/libraries/{library_id}/items", {
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
    async getLibraryRows(libraryId: number): Promise<HomepageRow[]> {
        const { data, error } = await client.GET("/api/v1/libraries/{library_id}/rows", {
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
