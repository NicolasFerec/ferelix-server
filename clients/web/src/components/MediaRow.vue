<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import type { MediaCardInfo } from "@/api/client";
import MediaCard from "./MediaCard.vue";

const props = defineProps<{ displayName: string; items: MediaCardInfo[]; sourceLibraryId?: number | string | null }>();
const scroller = ref<HTMLElement | null>(null);
const canPrevious = ref(false);
const canNext = ref(false);
let observer: ResizeObserver | undefined;
function updateArrows() {
  const element = scroller.value;
  if (!element) return;
  canPrevious.value = element.scrollLeft > 1;
  canNext.value = element.scrollLeft < element.scrollWidth - element.clientWidth - 2;
}
function scroll(direction: number) {
  const element = scroller.value;
  element?.scrollBy({ left: direction * element.clientWidth * .8, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
}
onMounted(() => { observer = new ResizeObserver(updateArrows); if (scroller.value) observer.observe(scroller.value); updateArrows(); });
onUnmounted(() => observer?.disconnect());
watch(() => props.items, async () => { await nextTick(); updateArrows(); });
</script>

<template>
  <section class="mb-10" :aria-label="displayName">
    <div class="mb-4 flex items-center justify-between gap-4">
      <h2 class="text-xl font-semibold tracking-tight">{{ displayName }}</h2>
      <div class="flex gap-2">
        <button type="button" :disabled="!canPrevious" :aria-label="$t('common.previous')" class="flex size-9 items-center justify-center rounded-full border border-outline text-gray-200 enabled:hover:bg-surface disabled:opacity-25" @click="scroll(-1)">‹</button>
        <button type="button" :disabled="!canNext" :aria-label="$t('common.next')" class="flex size-9 items-center justify-center rounded-full border border-outline text-gray-200 enabled:hover:bg-surface disabled:opacity-25" @click="scroll(1)">›</button>
      </div>
    </div>
    <div ref="scroller" class="ferelix-hide-scrollbar -mx-1 flex snap-x gap-4 overflow-x-auto px-1 pb-3 pt-1" @scroll.passive="updateArrows">
      <div v-for="item in items" :key="item.id" class="w-[150px] shrink-0 snap-start sm:w-[180px]"><MediaCard :media-file="item" :source-library-id="sourceLibraryId" /></div>
      <p v-if="!items.length" class="empty-state w-full">{{ $t('home.noItems') }}</p>
    </div>
  </section>
</template>
