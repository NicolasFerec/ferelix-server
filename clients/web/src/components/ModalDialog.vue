<script setup lang="ts">
import { onBeforeUnmount, onMounted, onUnmounted, ref } from "vue";

defineProps<{ label: string }>();
defineEmits<{ close: [] }>();
const dialog = ref<HTMLDialogElement | null>(null);
const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
onMounted(() => dialog.value?.showModal());
onBeforeUnmount(() => dialog.value?.close());
onUnmounted(() => {
  if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
});
</script>

<template>
  <dialog ref="dialog" :aria-label="label" class="fixed inset-0 m-0 h-full max-h-none w-full max-w-none items-center justify-center overflow-y-auto bg-black/70 p-4 text-foreground open:flex" @click.self="$emit('close')" @keydown.esc.stop.prevent="$emit('close')" @cancel.prevent="$emit('close')">
    <slot />
  </dialog>
</template>
