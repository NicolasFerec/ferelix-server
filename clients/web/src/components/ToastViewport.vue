<script setup lang="ts">
import { computed } from "vue";
import { type Toast, type ToastType, useToast } from "@/composables/useToast";

const { toasts, dismissToast } = useToast();

const toastTypeClass: Record<ToastType, string> = {
  default: "border-gray-700 bg-gray-950 text-gray-100",
  success: "border-green-700 bg-green-950 text-green-100",
  primary: "border-primary-600 bg-primary-900 text-primary-100",
  error: "border-red-700 bg-red-950 text-red-100",
  warn: "border-yellow-600 bg-yellow-950 text-yellow-100",
};

const progressClass: Record<ToastType, string> = {
  default: "bg-gray-300",
  success: "bg-green-400",
  primary: "bg-primary-400",
  error: "bg-red-400",
  warn: "bg-yellow-300",
};

const iconClass: Record<ToastType, string> = {
  default: "text-gray-300",
  success: "text-green-300",
  primary: "text-primary-300",
  error: "text-red-300",
  warn: "text-yellow-300",
};

const visibleToasts = computed(() => toasts.value);

function iconPath(type: ToastType): string {
  if (type === "success") return "M5 13l4 4L19 7";
  if (type === "error") return "M6 18L18 6M6 6l12 12";
  if (type === "warn") return "M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z";
  return "M13 16h-1v-4h-1m1-4h.01M12 22a10 10 0 110-20 10 10 0 010 20z";
}

function isWarnIcon(type: ToastType): boolean {
  return type === "warn";
}

function progressStyle(toast: Toast): Record<string, string> {
  return {
    animationDuration: `${toast.duration}ms`,
  };
}
</script>

<template>
  <teleport to="body">
    <div class="fixed bottom-5 right-5 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-3">
      <transition-group
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="translate-y-3 opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="translate-y-0 opacity-100"
        leave-to-class="translate-y-2 opacity-0"
      >
        <article
          v-for="toast in visibleToasts"
          :key="toast.id"
          class="relative overflow-hidden rounded-md border shadow-2xl"
          :class="toastTypeClass[toast.type]"
        >
          <div class="flex items-start gap-3 px-4 py-3">
            <svg
              class="mt-0.5 h-5 w-5 shrink-0"
              :class="iconClass[toast.type]"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                v-if="isWarnIcon(toast.type)"
                :d="iconPath(toast.type)"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
              />
              <path
                v-else
                :d="iconPath(toast.type)"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
              />
            </svg>
            <p class="min-w-0 flex-1 text-sm font-medium leading-5">{{ toast.message }}</p>
            <button
              type="button"
              class="-mr-1 rounded p-1 text-current opacity-70 transition-opacity hover:opacity-100"
              :aria-label="$t('common.close')"
              @click="dismissToast(toast.id)"
            >
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="h-1 bg-black/25">
            <div
              class="h-full origin-left animate-toast-progress"
              :class="progressClass[toast.type]"
              :style="progressStyle(toast)"
            />
          </div>
        </article>
      </transition-group>
    </div>
  </teleport>
</template>
