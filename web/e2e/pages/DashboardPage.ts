import { type Locator, type Page, expect } from "@playwright/test";

/**
 * Page Object Model for the Admin Dashboard page
 */
export class DashboardPage {
    readonly page: Page;
    readonly librariesTab: Locator;
    readonly jobsTab: Locator;
    readonly settingsTab: Locator;
    readonly usersTab: Locator;
    readonly recommendationsTab: Locator;
    readonly createLibraryButton: Locator;
    readonly libraryList: Locator;
    readonly libraryForm: Locator;
    readonly jobsList: Locator;
    readonly settingsForm: Locator;
    readonly usersList: Locator;
    readonly saveButton: Locator;
    readonly deleteButton: Locator;
    readonly confirmButton: Locator;
    readonly cancelButton: Locator;

    constructor(page: Page) {
        this.page = page;
        this.librariesTab = page.getByRole("tab", { name: /libraries/i });
        this.jobsTab = page.getByRole("tab", { name: /jobs/i });
        this.settingsTab = page.getByRole("tab", { name: /settings/i });
        this.usersTab = page.getByRole("tab", { name: /users/i });
        this.recommendationsTab = page.getByRole("tab", { name: /recommendations/i });
        this.createLibraryButton = page.getByRole("button", { name: /add|create|new/i });
        this.libraryList = page.locator("[data-testid=library-list], .library-list");
        this.libraryForm = page.locator("[data-testid=library-form], .library-form, form");
        this.jobsList = page.locator("[data-testid=jobs-list], .jobs-list");
        this.settingsForm = page.locator("[data-testid=settings-form], .settings-form, form");
        this.usersList = page.locator("[data-testid=users-list], .users-list");
        this.saveButton = page.getByRole("button", { name: /save/i });
        this.deleteButton = page.getByRole("button", { name: /delete/i });
        this.confirmButton = page.getByRole("button", { name: /confirm|yes/i });
        this.cancelButton = page.getByRole("button", { name: /cancel|no/i });
    }

    /**
     * Navigate to the dashboard page
     */
    async goto() {
        await this.page.goto("/dashboard");
    }

    /**
     * Assert dashboard is accessible
     */
    async expectToBeOnDashboard() {
        await expect(this.page).toHaveURL(/\/dashboard/);
    }

    /**
     * Assert access denied
     */
    async expectAccessDenied() {
        // Either redirected to login or shows 403
        const url = this.page.url();
        const hasAccessError =
            url.includes("/login") ||
            (await this.page.locator("text=/403|forbidden|access denied/i").isVisible().catch(() => false));
        expect(hasAccessError).toBe(true);
    }

    // Library Management
    /**
     * Go to libraries tab
     */
    async goToLibraries() {
        await this.librariesTab.click();
    }

    /**
     * Click create library button
     */
    async clickCreateLibrary() {
        await this.createLibraryButton.click();
    }

    /**
     * Fill library form
     */
    async fillLibraryForm(name: string, path: string, type = "movie") {
        await this.page.getByLabel(/name/i).fill(name);
        await this.page.getByLabel(/path/i).fill(path);
        if (type) {
            const typeSelect = this.page.getByLabel(/type/i);
            if (await typeSelect.isVisible()) {
                await typeSelect.selectOption(type);
            }
        }
    }

    /**
     * Save library
     */
    async saveLibrary() {
        await this.saveButton.click();
    }

    /**
     * Delete a library by name
     */
    async deleteLibrary(name: string) {
        const libraryRow = this.page.locator(`tr:has-text("${name}"), .library-item:has-text("${name}")`);
        await libraryRow.locator(this.deleteButton).click();
        await this.confirmButton.click();
    }

    /**
     * Trigger scan for a library
     */
    async scanLibrary(name: string) {
        const libraryRow = this.page.locator(`tr:has-text("${name}"), .library-item:has-text("${name}")`);
        await libraryRow.getByRole("button", { name: /scan/i }).click();
    }

    // Jobs Management
    /**
     * Go to jobs tab
     */
    async goToJobs() {
        await this.jobsTab.click();
    }

    /**
     * Get list of jobs
     */
    async getJobs(): Promise<string[]> {
        const jobs = await this.page.locator(".job-item, tr.job").allTextContents();
        return jobs;
    }

    /**
     * Trigger a job manually
     */
    async triggerJob(jobId: string) {
        const jobRow = this.page.locator(`tr:has-text("${jobId}"), .job-item:has-text("${jobId}")`);
        await jobRow.getByRole("button", { name: /trigger|run/i }).click();
    }

    /**
     * Cancel a running job
     */
    async cancelJob(jobId: string) {
        const jobRow = this.page.locator(`tr:has-text("${jobId}"), .job-item:has-text("${jobId}")`);
        await jobRow.getByRole("button", { name: /cancel|stop/i }).click();
    }

    // Settings Management
    /**
     * Go to settings tab
     */
    async goToSettings() {
        await this.settingsTab.click();
    }

    /**
     * Update a setting value
     */
    async updateSetting(settingLabel: string, value: string) {
        await this.page.getByLabel(settingLabel).fill(value);
    }

    /**
     * Save settings
     */
    async saveSettings() {
        await this.saveButton.click();
    }

    // User Management
    /**
     * Go to users tab
     */
    async goToUsers() {
        await this.usersTab.click();
    }

    /**
     * Get list of users
     */
    async getUsers(): Promise<string[]> {
        const users = await this.page.locator(".user-item, tr.user, [data-testid=user-row]").allTextContents();
        return users;
    }

    /**
     * Edit a user
     */
    async editUser(username: string) {
        const userRow = this.page.locator(`tr:has-text("${username}"), .user-item:has-text("${username}")`);
        await userRow.getByRole("button", { name: /edit/i }).click();
    }

    /**
     * Toggle user active status
     */
    async toggleUserActive(username: string) {
        const userRow = this.page.locator(`tr:has-text("${username}"), .user-item:has-text("${username}")`);
        await userRow.getByRole("checkbox").click();
    }

    // Recommendations Management
    /**
     * Go to recommendations tab
     */
    async goToRecommendations() {
        await this.recommendationsTab.click();
    }

    /**
     * Create a recommendation row
     */
    async createRecommendationRow(name: string, displayName: string, libraryId: number) {
        await this.page.getByRole("button", { name: /add|create|new/i }).click();
        await this.page.getByLabel(/name/i).fill(name);
        await this.page.getByLabel(/display name/i).fill(displayName);
        await this.page.getByLabel(/library/i).selectOption(String(libraryId));
        await this.saveButton.click();
    }

    /**
     * Delete a recommendation row
     */
    async deleteRecommendationRow(name: string) {
        const row = this.page.locator(`tr:has-text("${name}"), .recommendation-row:has-text("${name}")`);
        await row.locator(this.deleteButton).click();
        await this.confirmButton.click();
    }
}
