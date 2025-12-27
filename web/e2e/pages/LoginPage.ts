import { type Locator, type Page, expect } from "@playwright/test";

/**
 * Page Object Model for the Login page
 */
export class LoginPage {
    readonly page: Page;
    readonly usernameInput: Locator;
    readonly passwordInput: Locator;
    readonly loginButton: Locator;
    readonly errorMessage: Locator;

    constructor(page: Page) {
        this.page = page;
        // Use id selectors which are more reliable
        this.usernameInput = page.locator("#username");
        this.passwordInput = page.locator("#password");
        this.loginButton = page.locator("button[type='submit']");
        this.errorMessage = page.locator(".bg-red-900, [role=alert], .error-message");
    }

    /**
     * Navigate to the login page
     */
    async goto() {
        await this.page.goto("/login");
    }

    /**
     * Fill in login credentials
     */
    async fillCredentials(username: string, password: string) {
        await this.usernameInput.fill(username);
        await this.passwordInput.fill(password);
    }

    /**
     * Click the login button
     */
    async clickLogin() {
        await this.loginButton.click();
    }

    /**
     * Perform complete login
     */
    async login(username: string, password: string) {
        await this.fillCredentials(username, password);
        await this.clickLogin();
    }

    /**
     * Wait for redirect after successful login
     */
    async waitForRedirect(expectedPath = "/") {
        await this.page.waitForURL(new RegExp(expectedPath));
    }

    /**
     * Assert login error is displayed
     */
    async expectError(message?: string | RegExp) {
        await expect(this.errorMessage).toBeVisible();
        if (message) {
            await expect(this.errorMessage).toContainText(message);
        }
    }

    /**
     * Assert login page is displayed
     */
    async expectToBeOnLoginPage() {
        await expect(this.page).toHaveURL(/\/login/);
        await expect(this.usernameInput).toBeVisible();
        await expect(this.passwordInput).toBeVisible();
    }
}
