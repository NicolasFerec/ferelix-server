<script setup lang="ts">
import { computed } from "vue";
import { useFloatingDropdown } from "@/composables/useFloatingDropdown";

type DropdownValue = string | number | null;

export interface DropdownOption {
  value: DropdownValue;
  label: string;
}

const props = defineProps<{
  modelValue: DropdownValue;
  options: DropdownOption[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: DropdownValue];
}>();

const selectedLabel = computed(() => {
  return props.options.find((option) => option.value === props.modelValue)?.label || "";
});

const canOpen = computed(() => !props.disabled && props.options.length > 1);
const { isOpen, triggerRef, menuRef, menuStyle, toggle, close, onTriggerKeydown } = useFloatingDropdown({
  canOpen: () => canOpen.value,
});

function selectOption(value: DropdownValue): void {
  emit("update:modelValue", value);
  close();
  triggerRef.value?.focus();
}
</script>

<template>
  <button
    ref="triggerRef"
    type="button"
    class="dropdown-select__trigger"
    :disabled="!canOpen"
    :title="selectedLabel"
    @click="toggle"
    @keydown="onTriggerKeydown"
  >
    <span class="dropdown-select__label">{{ selectedLabel }}</span>
    <svg
      v-if="canOpen"
      class="dropdown-select__chevron"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
    >
      <path
        d="m6 8 4 4 4-4"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  </button>

  <Teleport to="body">
    <div
      v-if="isOpen"
      ref="menuRef"
      class="dropdown-select__menu"
      :style="menuStyle"
      @keydown.esc.stop.prevent="close"
    >
      <button
        v-for="option in options"
        :key="`${option.value}`"
        type="button"
        class="dropdown-select__option"
        :class="{ 'is-selected': option.value === modelValue }"
        :title="option.label"
        @click="selectOption(option.value)"
      >
        {{ option.label }}
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.dropdown-select__trigger {
  display: inline-flex;
  min-width: 0;
  max-width: min(42rem, 100%);
  align-items: center;
  gap: 0.25rem;
  border: 1px solid transparent;
  border-radius: 0.375rem;
  color: rgb(209 213 219);
  padding: 0.125rem 0.35rem;
  text-align: left;
  outline: none;
  transition:
    border-color 160ms ease,
    color 160ms ease;
}

.dropdown-select__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-select__trigger:hover:not(:disabled),
.dropdown-select__trigger:focus {
  border-color: rgba(59, 130, 246, 0.55);
  color: white;
}

.dropdown-select__trigger:disabled {
  cursor: default;
}

.dropdown-select__chevron {
  width: 1rem;
  height: 1rem;
  flex: 0 0 auto;
  color: rgb(156 163 175);
}

.dropdown-select__menu {
  position: fixed;
  z-index: 1000;
  width: max-content;
  overflow-x: hidden;
  overflow-y: auto;
  border-radius: 0.25rem;
  border: 1px solid rgb(55 65 81);
  background-color: rgb(17 24 39);
  box-shadow: 0 16px 36px rgba(0, 0, 0, 0.34);
}

.dropdown-select__option {
  display: block;
  width: 100%;
  overflow: hidden;
  padding: 0.32rem 1.75rem 0.32rem 0.5rem;
  color: rgb(229 231 235);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-select__option:hover,
.dropdown-select__option:focus,
.dropdown-select__option.is-selected {
  background-color: rgb(37 99 235);
  color: white;
}
</style>
