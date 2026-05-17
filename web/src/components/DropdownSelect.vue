<script setup lang="ts">
import { type CSSProperties, computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

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

const isOpen = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const menuRef = ref<HTMLDivElement | null>(null);
const menuStyle = ref<CSSProperties>({});

const selectedLabel = computed(() => {
  return props.options.find((option) => option.value === props.modelValue)?.label || "";
});

const canOpen = computed(() => !props.disabled && props.options.length > 1);

watch(isOpen, async (open) => {
  if (!open) return;

  await nextTick();
  updateMenuPosition();
});

function toggle(): void {
  if (!canOpen.value) return;

  isOpen.value = !isOpen.value;
}

function selectOption(value: DropdownValue): void {
  emit("update:modelValue", value);
  isOpen.value = false;
  triggerRef.value?.focus();
}

function close(): void {
  isOpen.value = false;
}

function onDocumentPointerDown(event: PointerEvent): void {
  const target = event.target as Node | null;
  if (!target) return;

  if (triggerRef.value?.contains(target) || menuRef.value?.contains(target)) {
    return;
  }

  close();
}

function updateMenuPosition(): void {
  if (!triggerRef.value || !menuRef.value) return;

  const margin = 12;
  const gap = 4;
  const triggerRect = triggerRef.value.getBoundingClientRect();
  const menuRect = menuRef.value.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const menuWidth = Math.min(menuRect.width, viewportWidth - margin * 2);
  const belowSpace = viewportHeight - triggerRect.bottom - gap - margin;
  const aboveSpace = triggerRect.top - gap - margin;
  const opensDown = belowSpace >= menuRect.height || belowSpace >= aboveSpace;
  const maxHeight = Math.max(120, opensDown ? belowSpace : aboveSpace);

  let left = triggerRect.left;
  if (left + menuWidth > viewportWidth - margin) {
    left = triggerRect.right - menuWidth;
  }
  left = Math.max(margin, Math.min(left, viewportWidth - margin - menuWidth));

  const naturalTop = opensDown ? triggerRect.bottom + gap : triggerRect.top - gap - menuRect.height;
  const top = opensDown ? naturalTop : Math.max(margin, naturalTop);

  menuStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    minWidth: `${triggerRect.width}px`,
    maxWidth: `${viewportWidth - margin * 2}px`,
    maxHeight: `${maxHeight}px`,
  };
}

function onTriggerKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    close();
    return;
  }

  if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
    event.preventDefault();
    if (!isOpen.value) {
      isOpen.value = canOpen.value;
    }
  }
}

onMounted(() => {
  document.addEventListener("pointerdown", onDocumentPointerDown);
  window.addEventListener("resize", updateMenuPosition);
  window.addEventListener("scroll", updateMenuPosition, true);
});

onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  window.removeEventListener("resize", updateMenuPosition);
  window.removeEventListener("scroll", updateMenuPosition, true);
});
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
