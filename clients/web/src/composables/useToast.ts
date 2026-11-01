import { computed, ref } from "vue";

export type ToastType = "default" | "success" | "primary" | "error" | "warn";

export interface Toast {
    id: number;
    message: string;
    type: ToastType;
    duration: number;
}

const toasts = ref<Toast[]>([]);
let nextToastId = 1;
const timers = new Map<number, ReturnType<typeof setTimeout>>();

function dismissToast(id: number): void {
    const timer = timers.get(id);
    if (timer) {
        clearTimeout(timer);
        timers.delete(id);
    }
    toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

function notify(message: string, type: ToastType = "default", duration = 4500): number {
    const id = nextToastId++;
    const toast = { id, message, type, duration };
    toasts.value = [...toasts.value, toast];

    const timer = setTimeout(() => dismissToast(id), duration);
    timers.set(id, timer);

    return id;
}

export function useToast() {
    return {
        toasts: computed(() => toasts.value),
        notify,
        dismissToast,
        default: (message: string, duration?: number) => notify(message, "default", duration),
        success: (message: string, duration?: number) => notify(message, "success", duration),
        primary: (message: string, duration?: number) => notify(message, "primary", duration),
        error: (message: string, duration?: number) => notify(message, "error", duration ?? 6000),
        warn: (message: string, duration?: number) => notify(message, "warn", duration),
    };
}
