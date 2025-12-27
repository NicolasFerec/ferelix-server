import { type Locator, type Page, expect } from "@playwright/test";

/**
 * Page Object Model for the Video Player page
 */
export class PlayerPage {
    readonly page: Page;
    readonly videoElement: Locator;
    readonly playButton: Locator;
    readonly pauseButton: Locator;
    readonly seekBar: Locator;
    readonly volumeSlider: Locator;
    readonly muteButton: Locator;
    readonly fullscreenButton: Locator;
    readonly settingsButton: Locator;
    readonly audioTrackSelector: Locator;
    readonly subtitleSelector: Locator;
    readonly qualitySelector: Locator;
    readonly infoPanel: Locator;
    readonly backButton: Locator;
    readonly loadingIndicator: Locator;
    readonly errorMessage: Locator;

    constructor(page: Page) {
        this.page = page;
        this.videoElement = page.locator("video");
        this.playButton = page.getByRole("button", { name: /play/i });
        this.pauseButton = page.getByRole("button", { name: /pause/i });
        this.seekBar = page.locator("input[type=range].seek-bar, .progress-bar");
        this.volumeSlider = page.locator("input[type=range].volume, .volume-slider");
        this.muteButton = page.getByRole("button", { name: /mute|unmute/i });
        this.fullscreenButton = page.getByRole("button", { name: /fullscreen/i });
        this.settingsButton = page.getByRole("button", { name: /settings/i });
        this.audioTrackSelector = page.locator("[data-testid=audio-tracks], .audio-track-selector");
        this.subtitleSelector = page.locator("[data-testid=subtitles], .subtitle-selector");
        this.qualitySelector = page.locator("[data-testid=quality], .quality-selector");
        this.infoPanel = page.locator("[data-testid=player-info], .player-info");
        this.backButton = page.getByRole("button", { name: /back|close/i });
        this.loadingIndicator = page.locator(".loading, .spinner, [data-testid=loading]");
        this.errorMessage = page.locator("[role=alert], .error, .player-error");
    }

    /**
     * Navigate to player page for a specific media
     */
    async goto(mediaId: number) {
        await this.page.goto(`/play/${mediaId}`);
    }

    /**
     * Wait for video to be ready
     */
    async waitForVideoReady() {
        await this.videoElement.waitFor({ state: "visible", timeout: 30000 });
        // Wait for video to have a source
        await this.page.waitForFunction(() => {
            const video = document.querySelector("video");
            return video && (video.src || video.currentSrc);
        }, { timeout: 30000 });
    }

    /**
     * Play the video
     */
    async play() {
        // Try clicking play button or the video itself
        try {
            await this.playButton.click({ timeout: 2000 });
        } catch {
            await this.videoElement.click();
        }
    }

    /**
     * Pause the video
     */
    async pause() {
        try {
            await this.pauseButton.click({ timeout: 2000 });
        } catch {
            await this.videoElement.click();
        }
    }

    /**
     * Check if video is playing
     */
    async isPlaying(): Promise<boolean> {
        return await this.page.evaluate(() => {
            const video = document.querySelector("video");
            return video ? !video.paused : false;
        });
    }

    /**
     * Get current playback time in seconds
     */
    async getCurrentTime(): Promise<number> {
        return await this.page.evaluate(() => {
            const video = document.querySelector("video");
            return video ? video.currentTime : 0;
        });
    }

    /**
     * Get video duration in seconds
     */
    async getDuration(): Promise<number> {
        return await this.page.evaluate(() => {
            const video = document.querySelector("video");
            return video ? video.duration : 0;
        });
    }

    /**
     * Seek to a specific time
     */
    async seekTo(seconds: number) {
        await this.page.evaluate((time) => {
            const video = document.querySelector("video");
            if (video) video.currentTime = time;
        }, seconds);
    }

    /**
     * Toggle mute
     */
    async toggleMute() {
        await this.muteButton.click();
    }

    /**
     * Set volume (0-1)
     */
    async setVolume(level: number) {
        await this.page.evaluate((vol) => {
            const video = document.querySelector("video");
            if (video) video.volume = vol;
        }, level);
    }

    /**
     * Toggle fullscreen
     */
    async toggleFullscreen() {
        await this.fullscreenButton.click();
    }

    /**
     * Press keyboard shortcut
     */
    async pressKey(key: string) {
        await this.page.keyboard.press(key);
    }

    /**
     * Press space to toggle play/pause
     */
    async togglePlayPause() {
        await this.pressKey("Space");
    }

    /**
     * Press M to toggle mute
     */
    async pressM() {
        await this.pressKey("m");
    }

    /**
     * Press F for fullscreen
     */
    async pressF() {
        await this.pressKey("f");
    }

    /**
     * Arrow right to seek forward
     */
    async seekForward() {
        await this.pressKey("ArrowRight");
    }

    /**
     * Arrow left to seek backward
     */
    async seekBackward() {
        await this.pressKey("ArrowLeft");
    }

    /**
     * Go back to previous page
     */
    async goBack() {
        await this.backButton.click();
    }

    /**
     * Wait for HLS segments to load
     */
    async waitForHlsReady(timeout = 30000) {
        // Wait for video to have buffered data
        await this.page.waitForFunction(
            () => {
                const video = document.querySelector("video");
                return video && video.buffered.length > 0;
            },
            { timeout },
        );
    }

    /**
     * Assert player is showing error
     */
    async expectError(message?: string | RegExp) {
        await expect(this.errorMessage).toBeVisible();
        if (message) {
            await expect(this.errorMessage).toContainText(message);
        }
    }

    /**
     * Get playback method from info panel
     */
    async getPlaybackMethod(): Promise<string | null> {
        // Open info panel if needed
        try {
            await this.infoPanel.waitFor({ state: "visible", timeout: 2000 });
        } catch {
            // Info panel might need to be opened
        }

        const text = await this.infoPanel.textContent();
        if (text?.includes("DirectPlay")) return "DirectPlay";
        if (text?.includes("DirectStream") || text?.includes("Remux")) return "DirectStream";
        if (text?.includes("Transcode")) return "Transcode";
        return null;
    }
}
