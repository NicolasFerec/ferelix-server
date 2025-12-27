import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for Ferelix E2E tests
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
    testDir: "./e2e/specs",
    /* Run tests sequentially to maintain state */
    fullyParallel: false,
    /* Use single worker to ensure test order */
    workers: 1,
    reporter: [
        ["list"],
        ["html", { outputFolder: "playwright-report" }],
    ],
    /* Shared settings for all the projects below. */
    use: {
        baseURL: "http://localhost:5173",
        trace: "on-first-retry",
        screenshot: "only-on-failure",
        video: "off",
    },

    /* Single project - tests run in alphabetical order by filename */
    projects: [
        {
            name: "chromium",
            use: { ...devices["Desktop Chrome"] },
        },
    ],

    /* Global setup starts servers and creates admin */
    globalSetup: "./e2e/global-setup.ts",
    globalTeardown: "./e2e/global-teardown.ts",

    /* No webServer - handled by globalSetup */

    timeout: 30 * 1000,
    expect: { timeout: 5 * 1000 },
});
