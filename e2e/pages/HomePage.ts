import { type Locator, type Page, expect } from "@playwright/test";

/**
 * Page Object Model for the Home page
 */
export class HomePage {
    readonly page: Page;
    readonly mediaRows: Locator;
    readonly mediaCards: Locator;
    readonly libraryLinks: Locator;
    readonly userMenu: Locator;
    readonly logoutButton: Locator;
    readonly settingsLink: Locator;
    readonly dashboardLink: Locator;

    constructor(page: Page) {
        this.page = page;
        this.mediaRows = page.locator("[data-testid=media-row], .media-row");
        this.mediaCards = page.locator("[data-testid=media-card], .media-card");
        this.libraryLinks = page.locator("nav a[href*=library], .library-link");
        this.userMenu = page.locator("[data-testid=user-menu], .user-menu");
        this.logoutButton = page.getByRole("button", { name: /logout|sign out/i });
        this.settingsLink = page.getByRole("link", { name: /settings/i });
        this.dashboardLink = page.getByRole("link", { name: /dashboard/i });
    }

    /**
     * Navigate to the home page
     */
    async goto() {
        await this.page.goto("/");
    }

    /**
     * Assert home page is displayed
     */
    async expectToBeOnHomePage() {
        await expect(this.page).toHaveURL(/^\/$|^\/home/);
    }

    /**
     * Wait for content to load
     */
    async waitForContentLoad() {
        // Wait for either media rows or an empty state message
        await this.page.waitForSelector(
            "[data-testid=media-row], .media-row, .empty-state, .no-content",
            { timeout: 10000 },
        ).catch(() => {
            // Content might not exist, that's OK
        });
    }

    /**
     * Get all media row titles
     */
    async getMediaRowTitles(): Promise<string[]> {
        const rows = await this.page.locator(".media-row-title, [data-testid=row-title]").all();
        return Promise.all(rows.map((row) => row.textContent() as Promise<string>));
    }

    /**
     * Click on a library link
     */
    async clickLibrary(libraryName: string) {
        await this.page.getByRole("link", { name: libraryName }).click();
    }

    /**
     * Click on a media card
     */
    async clickMediaCard(index = 0) {
        const cards = await this.mediaCards.all();
        if (cards.length > index) {
            await cards[index].click();
        }
    }

    /**
     * Open user menu
     */
    async openUserMenu() {
        await this.userMenu.click();
    }

    /**
     * Logout from the application
     */
    async logout() {
        await this.openUserMenu();
        await this.logoutButton.click();
    }

    /**
     * Navigate to settings
     */
    async goToSettings() {
        await this.openUserMenu();
        await this.settingsLink.click();
    }

    /**
     * Navigate to dashboard (admin only)
     */
    async goToDashboard() {
        await this.dashboardLink.click();
    }
}
