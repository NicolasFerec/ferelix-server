<script setup lang="ts">
defineProps<{
  canRetry?: boolean;
  isLoading: boolean;
  loadingMessage: string;
  errorMessage: string;
}>();

defineEmits<{
  retry: [];
  close: [];
}>();
</script>

<template>
  <div
    v-if="isLoading"
    role="status"
    class="absolute inset-0 flex flex-col items-center justify-center bg-black/60"
  >
    <div class="animate-spin rounded-full h-12 w-12 border-4 border-primary-500 border-t-transparent"></div>
    <p class="mt-4 text-white text-sm">{{ loadingMessage }}</p>
  </div>

  <div
    v-if="errorMessage"
    role="alert"
    class="absolute inset-0 z-60 flex flex-col items-center justify-center bg-black/80"
  >
    <svg aria-hidden="true" class="w-16 h-16 text-red-500 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
    <p class="mb-5 max-w-xl px-6 text-center text-base leading-relaxed text-white sm:text-lg">{{ errorMessage }}</p>
    <div class="flex gap-3">
      <button
        v-if="canRetry !== false"
        type="button"
        class="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
        @click="$emit('retry')"
      >
        {{ $t('player.retry') }}
      </button>
      <button
        type="button"
        class="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600"
        @click="$emit('close')"
      >
        {{ $t('player.close') }}
      </button>
    </div>
  </div>
</template>
