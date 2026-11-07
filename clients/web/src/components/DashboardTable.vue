<script setup lang="ts">
withDefaults(
  defineProps<{
    scrollable?: boolean;
    tableClass?: string;
  }>(),
  {
    scrollable: false,
    tableClass: "min-w-full divide-y divide-outline",
  },
);
</script>

<template>
  <div class="surface-panel overflow-hidden">
    <div :class="{ 'overflow-x-auto': scrollable }">
      <table :class="tableClass">
        <slot />
      </table>
    </div>
  </div>
</template>
