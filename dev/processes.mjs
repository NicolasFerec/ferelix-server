import { setTimeout } from 'node:timers/promises';

function signalGroup(pid, signal) {
    try {
        process.kill(-pid, signal);
        return true;
    } catch (error) {
        if (error.code !== 'ESRCH') throw error;
        return false;
    }
}

export async function terminateProcessGroups(groups, graceMs = 5000) {
    const remaining = new Set(groups);
    for (const pid of remaining) {
        if (!signalGroup(pid, 'SIGTERM')) remaining.delete(pid);
    }
    const deadline = Date.now() + graceMs;
    while (remaining.size && Date.now() < deadline) {
        await setTimeout(50);
        for (const pid of remaining) {
            if (!signalGroup(pid, 0)) remaining.delete(pid);
        }
    }
    // A launcher can exit before its descendants; retain group IDs until cleanup ends.
    for (const pid of remaining) signalGroup(pid, 'SIGKILL');
}
