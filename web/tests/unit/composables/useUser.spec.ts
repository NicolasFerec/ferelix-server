/**
 * Unit tests for useUser composable
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as apiClient from "@/api/client";
import { useUser } from "@/composables/useUser";

// Mock the API client module
vi.mock("@/api/client", () => ({
    auth: {
        getCurrentUser: vi.fn(),
    },
    isAuthenticated: vi.fn(),
}));

describe("useUser", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    describe("initial state", () => {
        it("should have null user initially", () => {
            vi.mocked(apiClient.isAuthenticated).mockReturnValue(false);

            const { user } = useUser();

            expect(user.value).toBeNull();
        });

        it("should have isAuthenticated as false when no user", () => {
            vi.mocked(apiClient.isAuthenticated).mockReturnValue(false);

            const { isAuthenticated } = useUser();

            expect(isAuthenticated.value).toBe(false);
        });

        it("should have isAdmin as false when no user", () => {
            vi.mocked(apiClient.isAuthenticated).mockReturnValue(false);

            const { isAdmin } = useUser();

            expect(isAdmin.value).toBe(false);
        });

        it("should have isLoading as false initially", () => {
            const { isLoading } = useUser();

            expect(isLoading.value).toBe(false);
        });
    });

    describe("loadUser", () => {
        it("should return null when not authenticated", async () => {
            vi.mocked(apiClient.isAuthenticated).mockReturnValue(false);

            const { loadUser } = useUser();
            const result = await loadUser();

            expect(result).toBeNull();
        });

        it("should load user when authenticated", async () => {
            const mockUser = {
                id: 1,
                username: "testuser",
                email: "test@example.com",
                is_admin: false,
                is_active: true,
                language: "en",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };

            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockResolvedValue(mockUser);

            const { loadUser, user } = useUser();
            const result = await loadUser();

            expect(result).toEqual(mockUser);
            expect(user.value).toEqual(mockUser);
        });

        it("should handle error when loading user fails", async () => {
            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockRejectedValue(new Error("Network error"));

            const { loadUser, user } = useUser();
            const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

            const result = await loadUser();

            expect(result).toBeNull();
            expect(user.value).toBeNull();
            consoleSpy.mockRestore();
        });
    });

    describe("clearUser", () => {
        it("should clear user data", async () => {
            const mockUser = {
                id: 1,
                username: "testuser",
                email: "test@example.com",
                is_admin: true,
                is_active: true,
                language: "en",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };

            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockResolvedValue(mockUser);

            const { loadUser, clearUser, user, isAuthenticated, isAdmin } = useUser();

            await loadUser();
            expect(user.value).toEqual(mockUser);

            clearUser();
            expect(user.value).toBeNull();
            expect(isAuthenticated.value).toBe(false);
            expect(isAdmin.value).toBe(false);
        });
    });

    describe("updateUser", () => {
        it("should update user data", async () => {
            const mockUser = {
                id: 1,
                username: "testuser",
                email: "test@example.com",
                is_admin: false,
                is_active: true,
                language: "en",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };

            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockResolvedValue(mockUser);

            const { loadUser, updateUser, user } = useUser();
            await loadUser();

            updateUser({ language: "fr" });

            expect(user.value?.language).toBe("fr");
        });
    });

    describe("isAdmin computed", () => {
        it("should return true when user is admin", async () => {
            const mockUser = {
                id: 1,
                username: "admin",
                email: "admin@example.com",
                is_admin: true,
                is_active: true,
                language: "en",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };

            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockResolvedValue(mockUser);

            const { loadUser, isAdmin } = useUser();
            await loadUser();

            expect(isAdmin.value).toBe(true);
        });

        it("should return false when user is not admin", async () => {
            const mockUser = {
                id: 1,
                username: "user",
                email: "user@example.com",
                is_admin: false,
                is_active: true,
                language: "en",
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            };

            vi.mocked(apiClient.isAuthenticated).mockReturnValue(true);
            vi.mocked(apiClient.auth.getCurrentUser).mockResolvedValue(mockUser);

            const { loadUser, isAdmin } = useUser();
            await loadUser();

            expect(isAdmin.value).toBe(false);
        });
    });
});
