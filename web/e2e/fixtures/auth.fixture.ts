import { test as base, type Page } from "@playwright/test";

/**
 * Test credentials for E2E tests
 * These must match the credentials created in auth.setup.ts
 */
export const TEST_ADMIN = {
    username: "admin",
    password: "adminpassword123",
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
    // Navigate to login page
    await page.goto("/login");
    
    // Wait for login page to load
    await page.waitForSelector('input[name="username"]', { timeout: 10000 });
    
    // Fill and submit login form
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole("button", { name: /login|sign in/i }).click();

    // Wait for redirect away from login
    await page.waitForURL((url) => !url.pathname.includes("/login"), {
        timeout: 10000,
    });
}

/**
 * Extended test with auth fixtures
 * Admin account is created by the setup test that runs first
 */
export const test = base.extend<AuthFixtures>({
    /**
     * Authenticated page as admin user
     * Assumes admin was created by setup tests
     */
    authenticatedPage: async ({ page }, use) => {
        await login(page, TEST_ADMIN.username, TEST_ADMIN.password);
        await use(page);
    },

    /**
     * Authenticated page as admin user (same as authenticatedPage for now)
     */
    adminPage: async ({ page }, use) => {
        await login(page, TEST_ADMIN.username, TEST_ADMIN.password);
        await use(page);
    },
});

export { expect } from "@playwright/test";
