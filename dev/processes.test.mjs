import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { terminateProcessGroups } from './processes.mjs';

test('stops descendants even if their launcher exits before them', { skip: process.platform !== 'linux' }, async () => {
    const childSource = "process.on('SIGTERM', () => {}); console.log(process.pid); setInterval(() => {}, 1000);";
    const parentSource = `
        const { spawn } = require('node:child_process');
        const child = spawn(process.execPath, ['-e', ${JSON.stringify(childSource)}], { stdio: ['ignore', 'pipe', 'ignore'] });
        child.stdout.pipe(process.stdout);
        process.on('SIGTERM', () => process.exit(0));
    `;
    const parent = spawn(process.execPath, ['-e', parentSource], { detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
    let grandchild;
    try {
        const [data] = await once(parent.stdout, 'data');
        grandchild = Number(data.toString().trim());
        const exited = once(parent, 'exit');
        await terminateProcessGroups([parent.pid], 150);
        await exited;
        // /proc can briefly retain a terminated orphan as a zombie until PID 1 reaps it.
        await new Promise((resolve) => setTimeout(resolve, 50));
        let state;
        try { state = readFileSync(`/proc/${grandchild}/stat`, 'utf8').split(' ')[2]; } catch (error) {
            if (error.code !== 'ENOENT') throw error;
        }
        assert.ok(state === undefined || state === 'Z', `Descendant still running: ${state}`);
    } finally {
        for (const pid of [parent.pid, grandchild]) {
            if (pid) { try { process.kill(pid, 'SIGKILL'); } catch {} }
        }
    }
});
