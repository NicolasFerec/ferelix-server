import { test, expect } from "../../fixtures/auth.fixture";

/**
 * Scenario: Admin sets up test library with sample media
 * This should run before media browsing/playback tests
 */
test.describe.serial("Library Setup (Admin)", () => {
    test("admin creates test library", async ({ adminPage }) => {
        await adminPage.goto("/dashboard");

        // Navigate to libraries tab
        await adminPage.getByRole("tab", { name: /libraries/i }).click();

        // Click create library
        await adminPage.getByRole("button", { name: /create|add.*library/i }).click();

        // Fill form
        await adminPage.getByLabel(/name/i).fill("Test Movies");
        await adminPage.getByLabel(/path/i).fill("/tmp/test-media");
        
        // Select type if dropdown exists
        const typeSelector = adminPage.getByLabel(/type/i);
        if (await typeSelector.isVisible().catch(() => false)) {
            await typeSelector.selectOption("movie");
        }

        // Save
        await adminPage.getByRole("button", { name: /save|create/i }).click();

        // Verify library appears
        await expect(adminPage.getByText("Test Movies")).toBeVisible();
    });

    // TODO: Add test media files
    // test("admin triggers library scan", async ({ adminPage }) => { ... });
});
