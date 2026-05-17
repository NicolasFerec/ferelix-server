<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

type MaskShape = "circle" | "square";

const props = withDefaults(
  defineProps<{
    currentImageUrl?: string | null;
    fallbackInitial?: string;
    mask?: MaskShape;
    aspectRatio?: number;
    outputSize?: number;
    accept?: string;
  }>(),
  {
    currentImageUrl: null,
    fallbackInitial: "?",
    mask: "square",
    aspectRatio: 1,
    outputSize: 512,
    accept: "image/png,image/jpeg,image/webp",
  },
);

const emit = defineEmits<{
  selected: [];
  remove: [];
}>();

const { t } = useI18n();
const fileInput = ref<HTMLInputElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const selectedImage = ref<HTMLImageElement | null>(null);
const objectUrl = ref<string | null>(null);
const zoom = ref(1);
const offsetX = ref(0);
const offsetY = ref(0);
const isDragging = ref(false);
const isTouchOverlayVisible = ref(false);
const lastPointer = ref({ x: 0, y: 0 });
const localError = ref("");

const previewSize = 220;
const hasSelectedImage = computed(() => Boolean(selectedImage.value));
const hasImage = computed(() => hasSelectedImage.value || Boolean(props.currentImageUrl));
const isCircle = computed(() => props.mask === "circle");
const safeInitial = computed(() => (props.fallbackInitial || "?").slice(0, 1).toUpperCase());

watch([selectedImage, zoom], () => {
  clampOffset();
  drawPreview();
});

watch(
  () => props.currentImageUrl,
  () => {
    if (!hasSelectedImage.value) {
      isTouchOverlayVisible.value = false;
    }
  },
);

function openFilePicker(): void {
  isTouchOverlayVisible.value = false;
  fileInput.value?.click();
}

async function handleFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;

  localError.value = "";
  if (!props.accept.split(",").map((type) => type.trim()).includes(file.type)) {
    localError.value = t("imageUpload.invalidImage");
    return;
  }

  clearSelectedImage();
  const url = URL.createObjectURL(file);
  const image = new Image();
  image.onload = async () => {
    selectedImage.value = image;
    objectUrl.value = url;
    zoom.value = 1;
    offsetX.value = 0;
    offsetY.value = 0;
    emit("selected");
    await nextTick();
    drawPreview();
  };
  image.onerror = () => {
    URL.revokeObjectURL(url);
    localError.value = t("imageUpload.invalidImage");
  };
  image.src = url;
}

function removeImage(): void {
  clearSelectedImage();
  localError.value = "";
  isTouchOverlayVisible.value = false;
  emit("remove");
}

function clearSelectedImage(): void {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value);
  }
  objectUrl.value = null;
  selectedImage.value = null;
  offsetX.value = 0;
  offsetY.value = 0;
  zoom.value = 1;
}

function resetSelection(): void {
  clearSelectedImage();
  localError.value = "";
  isTouchOverlayVisible.value = false;
}

function onPointerDown(event: PointerEvent): void {
  if (!selectedImage.value) return;
  isDragging.value = true;
  lastPointer.value = { x: event.clientX, y: event.clientY };
  canvas.value?.setPointerCapture(event.pointerId);
}

function revealOverlayForTouch(event: PointerEvent): void {
  if (event.pointerType !== "touch" || isTouchOverlayVisible.value) return;
  isTouchOverlayVisible.value = true;
  event.preventDefault();
  event.stopPropagation();
}

function onPointerMove(event: PointerEvent): void {
  if (!isDragging.value || !selectedImage.value) return;
  offsetX.value += event.clientX - lastPointer.value.x;
  offsetY.value += event.clientY - lastPointer.value.y;
  lastPointer.value = { x: event.clientX, y: event.clientY };
  clampOffset();
  drawPreview();
}

function onPointerUp(event: PointerEvent): void {
  isDragging.value = false;
  canvas.value?.releasePointerCapture(event.pointerId);
}

function clampOffset(): void {
  const image = selectedImage.value;
  if (!image) return;

  const { width, height } = scaledDimensions(previewSize, previewSize, image);
  const maxX = Math.max(0, (width - previewSize) / 2);
  const maxY = Math.max(0, (height - previewSize) / 2);
  offsetX.value = Math.min(maxX, Math.max(-maxX, offsetX.value));
  offsetY.value = Math.min(maxY, Math.max(-maxY, offsetY.value));
}

function drawPreview(): void {
  const previewCanvas = canvas.value;
  const image = selectedImage.value;
  if (!previewCanvas || !image) return;

  const context = previewCanvas.getContext("2d");
  if (!context) return;

  previewCanvas.width = previewSize;
  previewCanvas.height = previewSize;
  context.fillStyle = "#111827";
  context.fillRect(0, 0, previewSize, previewSize);
  drawImageToContext(context, image, previewSize, offsetX.value, offsetY.value);
}

function drawImageToContext(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  size: number,
  panX: number,
  panY: number,
): void {
  const { width, height } = scaledDimensions(size, size, image);
  const scale = size / previewSize;
  const left = (size - width) / 2 + panX * scale;
  const top = (size - height) / 2 + panY * scale;

  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, size, size);
  context.drawImage(image, left, top, width, height);
}

function scaledDimensions(width: number, height: number, image: HTMLImageElement): { width: number; height: number } {
  const baseScale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
  const scale = baseScale * zoom.value;
  return {
    width: image.naturalWidth * scale,
    height: image.naturalHeight * scale,
  };
}

async function getEditedFile(): Promise<File | null> {
  const image = selectedImage.value;
  if (!image) return null;

  const outputCanvas = document.createElement("canvas");
  outputCanvas.width = props.outputSize;
  outputCanvas.height = props.outputSize;
  const context = outputCanvas.getContext("2d");
  if (!context) return null;

  drawImageToContext(context, image, props.outputSize, offsetX.value, offsetY.value);

  const blob = await new Promise<Blob | null>((resolve) => {
    outputCanvas.toBlob(resolve, "image/jpeg", 0.92);
  });
  if (!blob) return null;

  return new File([blob], "profile-image.jpg", { type: "image/jpeg" });
}

defineExpose({
  getEditedFile,
  hasSelectedImage,
  resetSelection,
});

onBeforeUnmount(() => {
  clearSelectedImage();
});
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center">
      <div
        class="group relative flex shrink-0 items-center justify-center overflow-hidden bg-gray-700 text-3xl font-semibold text-gray-200"
        :class="[isCircle ? 'rounded-full' : 'rounded-md', hasSelectedImage ? 'h-56 w-56' : 'h-24 w-24']"
        @pointerdown.capture="revealOverlayForTouch"
      >
        <canvas
          v-if="hasSelectedImage"
          ref="canvas"
          :width="previewSize"
          :height="previewSize"
          class="h-full w-full touch-none object-cover"
          :class="isDragging ? 'cursor-grabbing' : 'cursor-grab'"
          :aria-label="t('imageUpload.cropPreview')"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        />
        <img
          v-else-if="currentImageUrl"
          :src="currentImageUrl"
          :alt="t('users.profileImage')"
          class="h-full w-full object-cover"
        />
        <span v-else>{{ safeInitial }}</span>

        <div
          class="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 bg-black/45 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
          :class="{ 'opacity-100': isTouchOverlayVisible }"
        >
          <button
            type="button"
            class="pointer-events-none inline-flex h-10 w-10 items-center justify-center rounded-full bg-gray-950/80 text-gray-100 shadow-lg ring-1 ring-white/15 transition-colors hover:bg-gray-800 group-hover:pointer-events-auto group-focus-within:pointer-events-auto"
            :class="{ 'pointer-events-auto': isTouchOverlayVisible }"
            :aria-label="t('imageUpload.chooseImage')"
            :title="t('imageUpload.chooseImage')"
            @click.stop="openFilePicker"
          >
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15.232 5.232l3.536 3.536M4 20h4.586a1 1 0 00.707-.293l9.9-9.9a2.5 2.5 0 00-3.536-3.536l-9.9 9.9A1 1 0 005.464 16.879L4 20z"
              />
            </svg>
          </button>
          <button
            v-if="hasImage"
            type="button"
            class="pointer-events-none inline-flex h-10 w-10 items-center justify-center rounded-full bg-red-950/80 text-red-100 shadow-lg ring-1 ring-white/15 transition-colors hover:bg-red-900 group-hover:pointer-events-auto group-focus-within:pointer-events-auto"
            :class="{ 'pointer-events-auto': isTouchOverlayVisible }"
            :aria-label="t('imageUpload.removeImage')"
            :title="t('imageUpload.removeImage')"
            @click.stop="removeImage"
          >
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7h6m-7 0a1 1 0 001-1h6a1 1 0 001 1m-8 0h8"
              />
            </svg>
          </button>
        </div>
      </div>

      <div v-if="hasSelectedImage" class="min-w-0 flex-1 space-y-3">
        <label v-if="hasSelectedImage" class="block">
          <span class="text-sm text-gray-300">{{ t("imageUpload.zoom") }}</span>
          <input
            v-model.number="zoom"
            class="mt-2 w-full accent-primary-500"
            type="range"
            min="1"
            max="4"
            step="0.01"
          />
        </label>
      </div>
    </div>

    <input ref="fileInput" class="sr-only" type="file" :accept="accept" @change="handleFileSelected" />

    <p v-if="localError" class="text-sm text-red-300">{{ localError }}</p>
  </div>
</template>
