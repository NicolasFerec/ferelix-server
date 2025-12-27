import { test, expect } from "@playwright/test";

test.describe("Setup Flow", () => {
    test("creates admin account", async ({ page }) => {
        // Check if setup is needed
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        if (!data.setup_complete) {
            // Create admin via API
            await page.request.post("/api/v1/setup/admin", {
                data: {
                    username: "admin",
                    password: "adminpassword123",
                },
            });

            // Verify setup is complete
            const verifyResponse = await page.request.get("/api/v1/setup/status");
            const verifyData = await verifyResponse.json();
            expect(verifyData.setup_complete).toBe(true);
        }
    });

    test("redirects from root to login when setup is complete", async ({ page }) => {
        await page.goto("/");

        // Should redirect to login (not setup)
        await page.waitForURL(/.*/);
        const url = page.url();
        expect(url).not.toContain("/setup");
    });

    test("redirects away from setup page when already complete", async ({ page }) => {
        // Setup is complete (admin created in global setup)
        await page.goto("/setup");

        // Should be redirected away from setup (to login or home)
        await page.waitForURL(/.*/);
        await expect(page).not.toHaveURL(/\/setup/);
    });

    test("setup status API returns complete", async ({ page }) => {
        // Verify that setup is marked as complete after setup test
        const response = await page.request.get("/api/v1/setup/status");
        const data = await response.json();

        expect(data.setup_complete).toBe(true);
    });
});
