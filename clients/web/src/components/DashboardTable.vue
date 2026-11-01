<script setup lang="ts">
withDefaults(
  defineProps<{
    scrollable?: boolean;
    tableClass?: string;
  }>(),
  {
    scrollable: false,
    tableClass: "min-w-full divide-y divide-gray-700",
  },
);
</script>

<template>
  <div class="overflow-hidden rounded-lg bg-gray-800">
    <div :class="{ 'overflow-x-auto': scrollable }">
      <table :class="tableClass">
        <slot />
      </table>
    </div>
  </div>
</template>
