<script setup lang="ts">
import { onMounted, onUnmounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type MediaFile } from "@/api/client";
import MediaCard from "./MediaCard.vue";

const props = defineProps<{
  displayName: string;
  items: MediaFile[];
}>();

const { t } = useI18n();

const scrollContainer: Ref<HTMLElement | null> = ref(null);
const showLeftArrow: Ref<boolean> = ref(false);
const showRightArrow: Ref<boolean> = ref(false);

function updateArrows(): void {
  if (!scrollContainer.value) return;

  const { scrollLeft, scrollWidth, clientWidth } = scrollContainer.value;
  showLeftArrow.value = scrollLeft > 0;
  showRightArrow.value = scrollLeft < scrollWidth - clientWidth - 10;
}

function scrollLeft(): void {
  if (scrollContainer.value) {
    scrollContainer.value.scrollBy({ left: -400, behavior: "smooth" });
  }
}

function scrollRight(): void {
  if (scrollContainer.value) {
    scrollContainer.value.scrollBy({ left: 400, behavior: "smooth" });
  }
}

function handleScroll(): void {
  updateArrows();
}

onMounted(() => {
  if (scrollContainer.value) {
    scrollContainer.value.addEventListener("scroll", handleScroll);
    updateArrows();
  }
});

onUnmounted(() => {
  if (scrollContainer.value) {
    scrollContainer.value.removeEventListener("scroll", handleScroll);
  }
});
</script>

<template>
  <div class="media-row mb-8">
    <h3 class="text-xl font-semibold mb-4 text-white px-6">{{ displayName }}</h3>
    <div class="relative">
      <div
        ref="scrollContainer"
        class="flex gap-4 overflow-x-auto scrollbar-hide px-6 pb-4"
        style="scroll-behavior: smooth"
      >
        <div v-for="item in items" :key="item.id" class="shrink-0 w-[200px]">
          <MediaCard :mediaFile="item" />
        </div>
        <div
          v-if="items.length === 0"
          class="flex items-center justify-center w-full h-64 text-gray-400"
        >
          {{ $t('home.noItems') }}
        </div>
      </div>
      <button
        v-if="showLeftArrow"
        @click="scrollLeft"
        class="absolute left-0 top-0 bottom-4 flex items-center justify-center w-12 bg-gray-900/80 hover:bg-gray-800/90 text-white rounded-r-lg transition-opacity z-10"
        :class="{ 'opacity-0': !showLeftArrow }"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M15 19l-7-7 7-7"
          />
        </svg>
      </button>
      <button
        v-if="showRightArrow"
        @click="scrollRight"
        class="absolute right-0 top-0 bottom-4 flex items-center justify-center w-12 bg-gray-900/80 hover:bg-gray-800/90 text-white rounded-l-lg transition-opacity z-10"
        :class="{ 'opacity-0': !showRightArrow }"
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
</style>
