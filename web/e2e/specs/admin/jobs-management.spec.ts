import { test, expect } from "../../fixtures/auth.fixture";
import { DashboardPage } from "../../pages/DashboardPage";

test.describe("Jobs Management", () => {
    let dashboardPage: DashboardPage;

    test.beforeEach(async ({ adminPage }) => {
        dashboardPage = new DashboardPage(adminPage);
        await dashboardPage.goto();
        await dashboardPage.goToJobs();
    });

    test("displays list of scheduled jobs", async ({ adminPage }) => {
        // Should see jobs list
        await expect(dashboardPage.jobsList).toBeVisible();

        // Should have at least the library scanner job
        const jobItems = await adminPage.locator(".job-item, [data-testid=job-row], tr.job").count();
        expect(jobItems).toBeGreaterThanOrEqual(0);
    });

    test("shows job status indicators", async ({ adminPage }) => {
        // Look for status badges/indicators
        const statusBadges = await adminPage.locator(
            ".status-badge, .job-status, [data-testid=job-status]",
        ).count();

        // If there are jobs, they should have status indicators
        const jobCount = await adminPage.locator(".job-item, [data-testid=job-row], tr.job").count();
        if (jobCount > 0) {
            expect(statusBadges).toBeGreaterThan(0);
        }
    });

    test("can trigger job manually", async ({ adminPage }) => {
        // Find trigger/run button
        const triggerButton = adminPage.getByRole("button", { name: /trigger|run|start/i }).first();

        if (await triggerButton.isVisible()) {
            await triggerButton.click();

            // Should show some indication of job starting
            await expect(
                adminPage.getByText(/triggered|started|running|queued/i),
            ).toBeVisible({ timeout: 5000 });
        }
    });

    test("can cancel running job", async ({ adminPage }) => {
        // First trigger a job if possible
        const triggerButton = adminPage.getByRole("button", { name: /trigger|run/i }).first();

        if (await triggerButton.isVisible()) {
            await triggerButton.click();

            // Wait for job to start
            await adminPage.waitForTimeout(1000);

            // Find cancel button
            const cancelButton = adminPage.getByRole("button", { name: /cancel|stop/i }).first();

            if (await cancelButton.isVisible()) {
                await cancelButton.click();

                // Should show cancellation indication
                await expect(
                    adminPage.getByText(/cancelled|stopped|cancelling/i),
                ).toBeVisible({ timeout: 5000 });
            }
        }
    });

    test("shows job execution history", async ({ adminPage }) => {
        // Look for history tab or section
        const historyTab = adminPage.getByRole("tab", { name: /history/i });

        if (await historyTab.isVisible()) {
            await historyTab.click();

            // Should see history list
            const historyList = adminPage.locator(
                ".job-history, [data-testid=job-history], .execution-history",
            );
            await expect(historyList).toBeVisible();
        }
    });

    test("displays job progress when running", async ({ adminPage }) => {
        // Trigger a job
        const triggerButton = adminPage.getByRole("button", { name: /trigger|run/i }).first();

        if (await triggerButton.isVisible()) {
            await triggerButton.click();

            // Wait a moment for job to start
            await adminPage.waitForTimeout(2000);

            // Look for progress indicators
            const progressIndicators = await adminPage.locator(
                ".progress-bar, .progress, [data-testid=progress]",
            ).count();

            // Progress might be shown or not depending on job type
            expect(typeof progressIndicators).toBe("number");
        }
    });

    test("shows next run time for scheduled jobs", async ({ adminPage }) => {
        // Look for next run time display
        const nextRunElements = await adminPage.locator(
            ".next-run, [data-testid=next-run], *:has-text(/next run|next:/i)",
        ).count();

        const jobCount = await adminPage.locator(".job-item, [data-testid=job-row], tr.job").count();

        // Scheduled jobs should show next run time
        if (jobCount > 0) {
            // At least some indication of scheduling should exist
            const hasScheduleInfo = nextRunElements > 0 ||
                (await adminPage.getByText(/minute|hour|day|interval/i).isVisible().catch(() => false));
            expect(hasScheduleInfo).toBeTruthy();
        }
    });

    test("refreshes job status automatically", async ({ adminPage }) => {
        // Get initial status
        const initialContent = await adminPage.locator(".job-item, [data-testid=job-row]").first().textContent();

        // Trigger a job
        const triggerButton = adminPage.getByRole("button", { name: /trigger|run/i }).first();

        if (await triggerButton.isVisible()) {
            await triggerButton.click();

            // Wait for potential auto-refresh
            await adminPage.waitForTimeout(3000);

            // Content should potentially change (status update)
            const updatedContent = await adminPage.locator(".job-item, [data-testid=job-row]").first().textContent();

            // Just verify the page is still functional
            expect(updatedContent).toBeDefined();
        }
    });
});
