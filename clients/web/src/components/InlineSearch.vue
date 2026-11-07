<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { type MediaCardInfo, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";

const route = useRoute();
const router = useRouter();
const root = ref<HTMLElement | null>(null);
const input = ref<HTMLInputElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const expanded = ref(false);
const query = ref("");
const items = ref<MediaCardInfo[]>([]);
const loading = ref(false);
const failed = ref(false);
const retry = ref(0);
const term = computed(() => query.value.trim());
const resultsLocation = computed(() => ({ name: "search", query: term.value ? { q: term.value } : {} }));
async function toggle() {
  expanded.value = !expanded.value;
  if (expanded.value) {
    query.value = typeof route.query.q === "string" ? route.query.q : query.value;
    await nextTick();
    input.value?.focus();
  }
}
function close(restoreFocus = false) {
  expanded.value = false;
  if (restoreFocus) trigger.value?.focus();
}
function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) close();
}
function focusOut(event: FocusEvent) {
  if (event.relatedTarget && !root.value?.contains(event.relatedTarget as Node)) close();
}
function moveResult(event: KeyboardEvent, direction: number) {
  const links = [...(root.value?.querySelectorAll<HTMLAnchorElement>("[data-search-result], [data-search-all]") || [])];
  if (!links.length) return;
  event.preventDefault();
  const index = links.indexOf(document.activeElement as HTMLAnchorElement);
  const next = index + direction;
  if (next < 0) input.value?.focus();
  else links[Math.min(next, links.length - 1)]?.focus();
}
async function showAll() {
  await router.push(resultsLocation.value);
  close();
}
watch([term, expanded, retry], ([value, open], _old, onCleanup) => {
  const controller = new AbortController();
  items.value = [];
  failed.value = false;
  loading.value = !!value && open;
  const timer = value && open ? setTimeout(async () => {
    try {
      const result = await media.search(value, 0, 5, controller.signal);
      if (!controller.signal.aborted) items.value = result;
    } catch {
      if (!controller.signal.aborted) failed.value = true;
    } finally {
      if (!controller.signal.aborted) loading.value = false;
    }
  }, 250) : undefined;
  onCleanup(() => { clearTimeout(timer); controller.abort(); });
});
watch(() => route.fullPath, () => close());
onMounted(() => document.addEventListener("pointerdown", outside));
onUnmounted(() => document.removeEventListener("pointerdown", outside));
</script>

<template>
  <search ref="root" :aria-label="$t('discovery.title')" class="relative" @focusout="focusOut" @keydown.esc.stop.prevent="close(true)">
    <button ref="trigger" type="button" class="flex size-10 items-center justify-center rounded-lg text-muted hover:bg-surface hover:text-white" :aria-label="$t('discovery.title')" :aria-expanded="expanded" aria-controls="inline-search-panel" @click="toggle">
      <svg aria-hidden="true" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>
    </button>
    <section v-if="expanded" id="inline-search-panel" :aria-label="$t('discovery.title')" class="fixed inset-x-3 top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto rounded-lg border border-white/10 bg-surface p-3 shadow-2xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-3 sm:w-96" @keydown.down="moveResult($event, 1)" @keydown.up="moveResult($event, -1)">
      <form @submit.prevent="showAll">
        <label for="inline-search-input" class="sr-only">{{ $t('discovery.searchLabel') }}</label>
        <input id="inline-search-input" ref="input" v-model="query" type="search" maxlength="200" autocomplete="off" class="field-input" :placeholder="$t('discovery.placeholder')" />
      </form>
      <p v-if="!term" class="px-2 py-5 text-sm text-muted">{{ $t('discovery.prompt') }}</p>
      <p v-else-if="loading" role="status" class="px-2 py-5 text-sm text-muted">{{ $t('common.loading') }}</p>
      <div v-else-if="failed" role="alert" class="px-2 py-5 text-sm"><p class="text-muted">{{ $t('discovery.searchFailed') }}</p><button class="mt-2 text-primary-300" type="button" @click="retry++">{{ $t('common.retry') }}</button></div>
      <template v-else-if="items.length">
        <h2 class="px-2 pb-2 pt-4 text-xs font-medium text-muted">{{ $t('discovery.bestMatches') }}</h2>
        <ul>
          <li v-for="item in items" :key="item.id">
            <RouterLink data-search-result :to="{name:'media-detail', params:{id:item.id}, query:{returnTo:router.resolve(resultsLocation).fullPath}}" class="flex items-center gap-3 rounded-sm p-2 hover:bg-white/5 focus-visible:bg-white/5">
              <img :src="media.getThumbnailUrl(item.id)" alt="" width="40" height="60" class="h-15 w-10 shrink-0 rounded-sm bg-background object-cover" />
              <span class="min-w-0"><span class="block truncate text-sm font-medium text-white">{{ getMediaTitleInfo(item.file_name).title }}</span><span class="text-xs text-muted">{{ getMediaTitleInfo(item.file_name).year }}</span></span>
            </RouterLink>
          </li>
        </ul>
      </template>
      <p v-else role="status" class="px-2 py-5 text-sm text-muted">{{ $t('discovery.empty', {query:term}) }}</p>
      <RouterLink v-if="term" data-search-all :to="resultsLocation" class="mt-2 block border-t border-white/10 px-2 pb-1 pt-3 text-sm font-medium text-primary-300" @click="close()">{{ $t('discovery.viewAll') }} →</RouterLink>
    </section>
  </search>
</template>
