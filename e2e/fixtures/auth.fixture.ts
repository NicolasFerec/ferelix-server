import { test as base, type Page } from "@playwright/test";

/**
 * Test credentials for E2E tests
 */
export const TEST_ADMIN = {
    username: "admin",
    password: "adminpassword123",
};

export const TEST_USER = {
    username: "testuser",
    password: "testpassword123",
};

/**
 * Auth fixture that provides authenticated pages
 */
export type AuthFixtures = {
    authenticatedPage: Page;
    adminPage: Page;
};

/**
 * Login helper function
 */
async function login(page: Page, username: string, password: string): Promise<void> {
    await page.goto("/login");
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole("button", { name: /login|sign in/i }).click();

    // Wait for redirect to home or dashboard
    await page.waitForURL(/^(?!.*\/login).*/);
}

/**
 * Setup helper - creates admin if needed, then logs in
 */
async function setupAndLogin(
    page: Page,
    username: string,
    password: string,
    isAdmin = false,
): Promise<void> {
    // Check if setup is required
    const response = await page.request.get("/api/v1/setup/status");
    const data = await response.json();

    if (!data.setup_complete) {
        // Create admin account first
        await page.goto("/setup");
        await page.getByLabel(/username/i).fill(TEST_ADMIN.username);
        await page.getByLabel(/password/i).fill(TEST_ADMIN.password);
        await page.getByRole("button", { name: /create|submit/i }).click();

        // Wait for redirect
        await page.waitForURL(/^(?!.*\/setup).*/);

        // If we need a non-admin user, logout and create one
        if (!isAdmin && username !== TEST_ADMIN.username) {
            // Would need to register via API or dashboard
            // For now, just use admin credentials
        }
    } else {
        // Setup already complete, just login
        await login(page, username, password);
    }
}

/**
 * Extended test with auth fixtures
 */
export const test = base.extend<AuthFixtures>({
    /**
     * Authenticated page as regular user
     * Uses admin credentials if no regular user exists
     */
    authenticatedPage: async ({ page }, use) => {
        await setupAndLogin(page, TEST_ADMIN.username, TEST_ADMIN.password);
        await use(page);
    },

    /**
     * Authenticated page as admin user
     */
    adminPage: async ({ page }, use) => {
        await setupAndLogin(page, TEST_ADMIN.username, TEST_ADMIN.password, true);
        await use(page);
    },
});

export { expect } from "@playwright/test";
