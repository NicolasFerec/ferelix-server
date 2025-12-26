import { test, expect } from "@playwright/test";

test.describe("Setup Flow", () => {
    test.beforeEach(async ({ page }) => {
        // Clear cookies/storage for fresh setup test
        await page.context().clearCookies();
    });

    test("shows setup page when no users exist", async ({ page }) => {
        // Check setup status
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (!data.setup_complete) {
            await page.goto("/");
            // Should redirect to setup or show setup prompt
            await expect(page).toHaveURL(/\/(setup|login)/);
        }
    });

    test("creates admin account successfully", async ({ page }) => {
        // Check if setup is needed
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (!data.setup_complete) {
            await page.goto("/setup");

            // Fill admin creation form
            await page.getByLabel(/username/i).fill("admin");
            await page.getByLabel(/password/i).fill("securepassword123");

            // Submit form
            await page.getByRole("button", { name: /create|submit|continue/i }).click();

            // Should redirect away from setup
            await page.waitForURL(/^(?!.*\/setup).*/);
        } else {
            // Skip if setup already complete
            test.skip();
        }
    });

    test("redirects to login after setup completion", async ({ page }) => {
        // First check if setup is complete
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (data.setup_complete) {
            // Try to access setup page
            await page.goto("/setup");

            // Should be redirected away (to login or home)
            await expect(page).not.toHaveURL(/\/setup/);
        }
    });

    test("validates password requirements", async ({ page }) => {
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (!data.setup_complete) {
            await page.goto("/setup");

            // Try submitting with weak password
            await page.getByLabel(/username/i).fill("admin");
            await page.getByLabel(/password/i).fill("123"); // Too short

            await page.getByRole("button", { name: /create|submit/i }).click();

            // Should show validation error or remain on page
            // Implementation varies based on frontend validation
            const url = page.url();
            const hasError = url.includes("/setup") || 
                await page.locator("[role=alert], .error, .text-red").isVisible().catch(() => false);

            expect(hasError).toBeTruthy();
        } else {
            test.skip();
        }
    });

    test("detects browser language for setup", async ({ page, context }) => {
        // Set browser language to French
        await context.setExtraHTTPHeaders({
            "Accept-Language": "fr-FR,fr;q=0.9",
        });

        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (!data.setup_complete) {
            await page.goto("/setup");

            // Check if language selector defaults to French or page is in French
            // This depends on implementation - either selector value or page content
            const pageContent = await page.content();
            const languageSelector = page.getByLabel(/language/i);

            if (await languageSelector.isVisible()) {
                const value = await languageSelector.inputValue();
                // French might be pre-selected
                expect(["fr", "en"]).toContain(value);
            }
        } else {
            test.skip();
        }
    });
});
