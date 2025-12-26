/**
 * Vitest global test setup
 */
import { config } from "@vue/test-utils";
import { createI18n } from "vue-i18n";

// Mock i18n for tests
const i18n = createI18n({
    legacy: false,
    locale: "en",
    fallbackLocale: "en",
    messages: {
        en: {
            // Add minimal translations for tests
            common: {
                loading: "Loading...",
                error: "Error",
                save: "Save",
                cancel: "Cancel",
                delete: "Delete",
                edit: "Edit",
                create: "Create",
                back: "Back",
                submit: "Submit",
            },
            auth: {
                login: "Login",
                logout: "Logout",
                username: "Username",
                password: "Password",
                register: "Register",
            },
            nav: {
                home: "Home",
                settings: "Settings",
                dashboard: "Dashboard",
            },
            player: {
                play: "Play",
                pause: "Pause",
                stop: "Stop",
                mute: "Mute",
                unmute: "Unmute",
            },
        },
    },
});

// Configure global plugins for Vue Test Utils
config.global.plugins = [i18n];

// Mock window.matchMedia
Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
    }),
});

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
};

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
    readonly root: Element | null = null;
    readonly rootMargin: string = "";
    readonly thresholds: readonly number[] = [];

    constructor() {}

    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] {
        return [];
    }
};

// Mock localStorage
const localStorageMock = {
    getItem: (key: string) => null,
    setItem: (key: string, value: string) => {},
    removeItem: (key: string) => {},
    clear: () => {},
    length: 0,
    key: (index: number) => null,
};
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// Mock sessionStorage
Object.defineProperty(window, "sessionStorage", { value: localStorageMock });

// Suppress console.error during tests unless debugging
const originalConsoleError = console.error;
console.error = (...args: any[]) => {
    // Filter out Vue warnings that are expected in tests
    const message = args[0]?.toString?.() || "";
    if (
        message.includes("[Vue warn]") ||
        message.includes("Failed to resolve component")
    ) {
        return;
    }
    originalConsoleError.apply(console, args);
};
