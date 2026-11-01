import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { terminateProcessGroups } from './processes.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
process.chdir(root);
// Shell variables take precedence; component-local files override root files.
const shellEnv = { ...process.env };
function environment(directory) {
    const result = {};
    for (const file of ['.env', '.env.local', `${directory}/.env`, `${directory}/.env.local`]) {
        if (existsSync(file)) Object.assign(result, parseEnv(readFileSync(file, 'utf8')));
    }
    return { ...result, ...shellEnv };
}

async function assertFree(port) {
    for (const host of ['127.0.0.1', 'localhost']) await new Promise((resolve, reject) => {
        const server = createServer();
        server.once('error', () => reject(new Error(`Port ${port} already in use. Stop the existing server first.`)));
        server.listen(port, host, () => server.close(resolve));
    });
}

const children = new Set();
const processGroups = new Set();
let stopping = false;
function stop(code) {
    if (stopping) return;
    stopping = true;
    process.exitCode = code;
    void terminateProcessGroups(processGroups).catch((error) => {
        console.error('Could not stop development processes:', error.message);
        process.exitCode = 1;
    });
}
function run(command, args, directory, env) {
    const child = spawn(command, args, { cwd: `${root}/${directory}`, env, stdio: 'inherit', detached: true });
    children.add(child);
    if (child.pid) processGroups.add(child.pid);
    child.once('error', (error) => { children.delete(child); console.error(error.message); stop(1); });
    child.once('exit', (code) => { children.delete(child); if (!stopping) stop(code ?? 1); });
    return child;
}
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

try {
    const serverOnly = process.argv.includes('--server-only');
    await assertFree(8005);
    if (!serverOnly) await assertFree(5187);
    const backendEnv = environment('server');
    // Migrations and server must use the same directory and environment.
    const migration = spawn('uv', ['run', 'alembic', 'upgrade', 'head'], {
        cwd: `${root}/server`, env: backendEnv, stdio: 'inherit', detached: true,
    });
    children.add(migration);
    if (migration.pid) processGroups.add(migration.pid);
    await new Promise((resolve, reject) => {
        migration.once('error', (error) => { children.delete(migration); reject(error); });
        migration.once('exit', (code) => {
            children.delete(migration);
            if (code === 0) processGroups.delete(migration.pid);
            code === 0 ? resolve() : reject(new Error('Database migration failed.'));
        });
    });
    if (!stopping) {
        run('uv', ['run', 'uvicorn', 'app.main:app', '--reload', '--reload-dir', 'app', '--port', '8005'], 'server', backendEnv);
        if (!serverOnly) run('pnpm', ['dev', '--strictPort'], 'web', environment('web'));
        console.log('Ferelix: http://localhost:5187 — API: http://localhost:8005/docs');
    }
} catch (error) {
    console.error(error.message);
    stop(1);
}
