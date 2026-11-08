import { onUnmounted, ref } from "vue";

/** A cancellable countdown owned by one player route, started only by its ended handler. */
export function usePlaybackCountdown(onComplete: () => void, durationSeconds = 10) {
    const active = ref(false);
    const remaining = ref(durationSeconds);
    let timer: ReturnType<typeof setInterval> | undefined;
    let deadline = 0;

    function cancel() {
        clearInterval(timer);
        timer = undefined;
        active.value = false;
    }
    function start() {
        cancel();
        remaining.value = durationSeconds;
        deadline = Date.now() + durationSeconds * 1000;
        active.value = true;
        timer = setInterval(() => {
            remaining.value = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            if (remaining.value === 0) {
                cancel();
                onComplete();
            }
        }, 250);
    }
    onUnmounted(cancel);
    return { active, remaining, start, cancel };
}
