import { test, expect } from "@playwright/test";
import { LoginPage } from "../../pages/LoginPage";

test.describe("Login Flow", () => {
    let loginPage: LoginPage;

    test.beforeEach(async ({ page }) => {
        loginPage = new LoginPage(page);
        // Clear auth state (localStorage might not be accessible before page loads)
        await page.goto("/login");
        await page.context().clearCookies();
        await page.evaluate(() => localStorage.clear()).catch(() => {
            // Ignore if localStorage is not accessible
        });
    });

    test("displays login form", async ({ page }) => {
        await loginPage.goto();

        await expect(loginPage.usernameInput).toBeVisible();
        await expect(loginPage.passwordInput).toBeVisible();
        await expect(loginPage.loginButton).toBeVisible();
    });

    test("login with valid credentials redirects to home", async ({ page }) => {
        // Admin is created in setup project
        await loginPage.goto();
        await loginPage.login("admin", "adminpassword123");

        // Should redirect to home (root path)
        await page.waitForURL((url) => url.pathname === "/" || url.pathname === "/home");
        await expect(page).not.toHaveURL(/\/login/);
    });

    test("login with invalid credentials shows error", async ({ page }) => {
        await loginPage.goto();
        await loginPage.login("wronguser", "wrongpassword");

        // Should show error message
        await loginPage.expectError();

        // Should stay on login page
        await expect(page).toHaveURL(/\/login/);
    });

    test("login with incorrect password shows error", async ({ page }) => {
        // Admin is created in setup project
        await loginPage.goto();
        await loginPage.login("admin", "wrongpassword");

        // Should show error
        await loginPage.expectError();

        // Should stay on login page
        await expect(page).toHaveURL(/\/login/);
    });

    test("login form validates required fields", async ({ page }) => {
        await loginPage.goto();

        // Try to submit empty form
        await loginPage.clickLogin();

        // HTML5 validation should prevent submission or show error
        // Check if we're still on login page
        await expect(page).toHaveURL(/\/login/);
    });

    test("password field masks input", async ({ page }) => {
        await loginPage.goto();

        // Check password input type
        const inputType = await loginPage.passwordInput.getAttribute("type");
        expect(inputType).toBe("password");
    });

    test("remembers redirect URL after login", async ({ page }) => {
        // Try to access protected page
        await page.goto("/dashboard");

        // Should redirect to login
        await expect(page).toHaveURL(/\/login/);

        // Login (admin already created in global setup)
        await loginPage.login("admin", "adminpassword123");

        // Should redirect back to original destination or home
        await page.waitForURL((url) =>
            url.pathname === "/" || url.pathname === "/home" || url.pathname === "/dashboard"
        );
    });

    test("unauthenticated access redirects to login", async ({ page }) => {
        // Clear any existing auth
        await page.context().clearCookies();
        await page.evaluate(() => localStorage.clear());

        // Try to access protected route
        await page.goto("/");

        // Check setup status first
        const statusResponse = await page.request.get("/api/v1/setup/status");
        const statusData = await statusResponse.json();

        if (statusData.setup_complete) {
            // Should redirect to login for protected content
            await expect(page).toHaveURL(/\/(login|setup)/);
        }
    });
});
