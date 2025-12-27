import { type ChildProcess, spawn } from "child_process";
import { existsSync, unlinkSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";
import { request } from "@playwright/test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const BACKEND_URL = "http://localhost:8000";
const FRONTEND_URL = "http://localhost:5173";

// Unique database file for this test run
const DB_FILE = join(__dirname, `../../server/e2e_test_${Date.now()}.db`);

async function waitForServer(url: string, timeout = 60000): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        try {
            const res = await fetch(url);
            if (res.ok) return;
        } catch {
            // Server not ready yet
        }
        await new Promise((r) => setTimeout(r, 500));
    }
    throw new Error(`Server at ${url} did not start within ${timeout}ms`);
}

async function runMigrations(): Promise<void> {
    console.log("Running database migrations...");
    return new Promise((resolve, reject) => {
        const proc = spawn("uv", ["run", "--no-sync", "alembic", "upgrade", "head"], {
            cwd: join(__dirname, "../../server"),
            env: { ...process.env, DATABASE_URL: `sqlite+aiosqlite:///${DB_FILE}` },
            stdio: "inherit",
        });
        proc.on("close", (code) => {
            if (code === 0) resolve();
            else reject(new Error(`Migrations failed with code ${code}`));
        });
        proc.on("error", reject);
    });
}

function startBackendServer(): ChildProcess {
    console.log(`Starting backend with database: ${DB_FILE}`);
    const proc = spawn("uv", ["run", "--no-sync", "fastapi", "dev"], {
        cwd: join(__dirname, "../../server"),
        env: { ...process.env, DATABASE_URL: `sqlite+aiosqlite:///${DB_FILE}` },
        stdio: process.env.DEBUG ? "inherit" : "pipe",
    });
    return proc;
}

function startFrontendServer(): ChildProcess {
    console.log("Starting frontend...");
    const proc = spawn("pnpm", ["dev"], {
        cwd: join(__dirname, ".."),
        stdio: process.env.DEBUG ? "inherit" : "pipe",
    });
    return proc;
}

async function createAdmin(): Promise<void> {
    const context = await request.newContext({ baseURL: BACKEND_URL });

    const status = await context.get("/api/v1/setup/status");
    const { setup_complete } = await status.json();

    if (!setup_complete) {
        console.log("Creating admin account...");
        const response = await context.post("/api/v1/setup/admin", {
            data: { username: "admin", password: "adminpassword123", language: "en" },
        });
        if (!response.ok()) {
            throw new Error(`Failed to create admin: ${await response.text()}`);
        }
        console.log("Admin account created");
    } else {
        console.log("Admin already exists");
    }

    await context.dispose();
}

export default async function globalSetup(): Promise<void> {
    console.log("\n=== E2E Global Setup ===\n");

    // Clean up any leftover database
    if (existsSync(DB_FILE)) {
        unlinkSync(DB_FILE);
    }

    await runMigrations();

    const backendProcess = startBackendServer();
    await waitForServer(`${BACKEND_URL}/api/v1/setup/status`);
    console.log("Backend ready");

    const frontendProcess = startFrontendServer();
    await waitForServer(FRONTEND_URL);
    console.log("Frontend ready");

    await createAdmin();

    // Store for teardown
    (globalThis as Record<string, unknown>).__e2e = {
        backendProcess,
        frontendProcess,
        dbFile: DB_FILE,
    };

    console.log("\n=== Setup Complete ===\n");
}
