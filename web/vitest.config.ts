import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
    plugins: [vue()],
    test: {
        environment: "jsdom",
        globals: true,
        include: ["tests/**/*.spec.ts"],
        exclude: ["node_modules", "dist"],
        coverage: {
            provider: "v8",
            reporter: ["text", "json", "html"],
            include: ["src/**/*.{ts,vue}"],
            exclude: ["src/**/*.d.ts", "src/api/types.ts"],
        },
        setupFiles: ["tests/setup.ts"],
    },
    resolve: {
        alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
        },
    },
});
