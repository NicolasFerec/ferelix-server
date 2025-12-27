import type { ChildProcess } from "child_process";
import { existsSync, unlinkSync } from "fs";

interface E2EState {
    backendProcess: ChildProcess;
    frontendProcess: ChildProcess;
    dbFile: string;
}

export default async function globalTeardown(): Promise<void> {
    console.log("\n=== E2E Global Teardown ===\n");

    const state = (globalThis as Record<string, unknown>).__e2e as E2EState | undefined;

    if (state) {
        // Kill servers
        if (state.backendProcess) {
            console.log("Stopping backend...");
            state.backendProcess.kill("SIGTERM");
        }
        if (state.frontendProcess) {
            console.log("Stopping frontend...");
            state.frontendProcess.kill("SIGTERM");
        }

        // Clean up database file
        if (state.dbFile && existsSync(state.dbFile)) {
            console.log(`Removing database: ${state.dbFile}`);
            unlinkSync(state.dbFile);
        }
    }

    console.log("\n=== Teardown Complete ===\n");
}
