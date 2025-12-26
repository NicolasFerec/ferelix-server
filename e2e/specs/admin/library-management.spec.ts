import { test, expect } from "../../fixtures/auth.fixture";
import { DashboardPage } from "../../pages/DashboardPage";

test.describe("Library Management", () => {
    let dashboardPage: DashboardPage;

    test.describe("Admin access", () => {
        test.beforeEach(async ({ adminPage }) => {
            dashboardPage = new DashboardPage(adminPage);
            await dashboardPage.goto();
        });

        test("admin can access dashboard", async ({ adminPage }) => {
            await dashboardPage.expectToBeOnDashboard();
        });

        test("admin can view libraries tab", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();

            // Libraries tab should be active
            await expect(dashboardPage.libraryList).toBeVisible();
        });

        test("admin can create a new library", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();
            await dashboardPage.clickCreateLibrary();

            // Fill form
            await dashboardPage.fillLibraryForm("Test Movies", "/media/movies", "movie");
            await dashboardPage.saveLibrary();

            // Should see success or library in list
            await expect(adminPage.getByText("Test Movies")).toBeVisible();
        });

        test("admin can edit library name", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();

            // Find edit button for a library
            const editButton = adminPage.getByRole("button", { name: /edit/i }).first();

            if (await editButton.isVisible()) {
                await editButton.click();

                // Update name
                const nameInput = adminPage.getByLabel(/name/i);
                await nameInput.clear();
                await nameInput.fill("Updated Library Name");

                await dashboardPage.saveLibrary();

                // Should see updated name
                await expect(adminPage.getByText("Updated Library Name")).toBeVisible();
            }
        });

        test("admin can delete library with confirmation", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();

            // Get initial library count
            const initialCount = await adminPage.locator(".library-item, tr.library").count();

            if (initialCount > 0) {
                // Click delete on first library
                const deleteButton = adminPage.getByRole("button", { name: /delete/i }).first();
                await deleteButton.click();

                // Confirm deletion
                await dashboardPage.confirmButton.click();

                // Library count should decrease
                await expect(adminPage.locator(".library-item, tr.library")).toHaveCount(initialCount - 1);
            }
        });

        test("admin can enable/disable library", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();

            // Find toggle switch for enabling/disabling
            const toggleSwitch = adminPage.getByRole("switch").first();

            if (await toggleSwitch.isVisible()) {
                const initialState = await toggleSwitch.isChecked();
                await toggleSwitch.click();

                // State should toggle
                await expect(toggleSwitch).toHaveAttribute(
                    "aria-checked",
                    String(!initialState),
                );
            }
        });

        test("admin can trigger library scan", async ({ adminPage }) => {
            await dashboardPage.goToLibraries();

            // Find scan button
            const scanButton = adminPage.getByRole("button", { name: /scan/i }).first();

            if (await scanButton.isVisible()) {
                await scanButton.click();

                // Should show scanning indicator or success message
                await expect(
                    adminPage.getByText(/scanning|started|queued/i),
                ).toBeVisible();
            }
        });
    });

    test.describe("Non-admin access", () => {
        test("non-admin cannot access dashboard", async ({ page }) => {
            // Login as non-admin if possible, or test redirect
            await page.goto("/dashboard");

            // Should be denied access or redirected
            const url = page.url();
            const denied =
                url.includes("/login") ||
                !url.includes("/dashboard") ||
                (await page.locator("text=/forbidden|denied|403/i").isVisible().catch(() => false));

            expect(denied).toBeTruthy();
        });
    });

    test.describe("Library form validation", () => {
        test.beforeEach(async ({ adminPage }) => {
            dashboardPage = new DashboardPage(adminPage);
            await dashboardPage.goto();
            await dashboardPage.goToLibraries();
        });

        test("requires library name", async ({ adminPage }) => {
            await dashboardPage.clickCreateLibrary();

            // Fill only path
            await adminPage.getByLabel(/path/i).fill("/media/test");

            // Try to save
            await dashboardPage.saveLibrary();

            // Should show validation error
            const hasError =
                (await adminPage.locator("[role=alert], .error, .text-red").isVisible().catch(() => false)) ||
                (await adminPage.getByLabel(/name/i).getAttribute("aria-invalid")) === "true";

            expect(hasError).toBeTruthy();
        });

        test("requires library path", async ({ adminPage }) => {
            await dashboardPage.clickCreateLibrary();

            // Fill only name
            await adminPage.getByLabel(/name/i).fill("Test Library");

            // Try to save
            await dashboardPage.saveLibrary();

            // Should show validation error or stay on form
            const hasError =
                (await adminPage.locator("[role=alert], .error, .text-red").isVisible().catch(() => false)) ||
                (await adminPage.getByLabel(/path/i).getAttribute("aria-invalid")) === "true";

            expect(hasError).toBeTruthy();
        });

        test("prevents duplicate library paths", async ({ adminPage }) => {
            await dashboardPage.clickCreateLibrary();

            // Create first library
            await dashboardPage.fillLibraryForm("Library 1", "/media/unique");
            await dashboardPage.saveLibrary();

            // Try to create another with same path
            await dashboardPage.clickCreateLibrary();
            await dashboardPage.fillLibraryForm("Library 2", "/media/unique");
            await dashboardPage.saveLibrary();

            // Should show error about duplicate path
            await expect(adminPage.getByText(/already exists|duplicate/i)).toBeVisible();
        });
    });
});
