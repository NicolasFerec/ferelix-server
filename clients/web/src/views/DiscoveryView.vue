<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { type MediaCardInfo, media, watchlist } from "@/api/client";
import MediaCard from "@/components/MediaCard.vue";
import MenuBar from "@/components/MenuBar.vue";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const isSearch = computed(() => route.name === "search");
const query = computed(() => typeof route.query.q === "string" ? route.query.q.trim().slice(0, 200) : "");
const page = computed(() => Math.max(1, Math.min(1000000, Math.floor(Number(route.query.page) || 1))));
const searchInput = ref(query.value);
const searchField = ref<HTMLInputElement | null>(null);
const items = ref<MediaCardInfo[]>([]);
const fetching = ref(false);
const debouncing = ref(false);
const error = ref("");
const hasNext = ref(false);
const revision = ref(0);
const loading = computed(() => fetching.value || debouncing.value);
let request: AbortController | undefined;
let debounce: ReturnType<typeof setTimeout> | undefined;

function changeQuery() {
  clearTimeout(debounce);
  debouncing.value = false;
  const q = searchInput.value.trim();
  if (q === query.value) return;
  void router.replace({ name: "search", query: q ? { q } : {} });
}
function destination(targetPage: number) {
  return { query: { ...(isSearch.value && query.value ? {q: query.value} : {}), page: String(targetPage) } };
}
watch(searchInput, value => {
  clearTimeout(debounce);
  if (!isSearch.value || value.trim() === query.value) { debouncing.value = false; return; }
  debouncing.value = true;
  debounce = setTimeout(changeQuery, 300);
});
watch(() => [route.name, query.value, page.value, revision.value], async (_, _old, onCleanup) => {
  clearTimeout(debounce);
  debouncing.value = false;
  searchInput.value = query.value;
  const controller = new AbortController();
  request = controller;
  onCleanup(() => controller.abort());
  error.value = "";
  if (isSearch.value && !query.value) {
    items.value = [];
    fetching.value = false;
    hasNext.value = false;
    return;
  }
  fetching.value = true;
  try {
    const cards = isSearch.value
      ? await media.search(query.value, (page.value - 1) * 48, 49, controller.signal)
      : await watchlist.list((page.value - 1) * 48, 49, controller.signal);
    controller.signal.throwIfAborted();
    hasNext.value = cards.length > 48;
    items.value = cards.slice(0, 48);
  } catch {
    if (!controller.signal.aborted) error.value = t(isSearch.value ? "discovery.searchFailed" : "watchlist.loadFailed");
  } finally {
    if (!controller.signal.aborted) fetching.value = false;
  }
}, { immediate: true });
onMounted(() => { if (isSearch.value) searchField.value?.focus({preventScroll:true}); });
onUnmounted(() => { clearTimeout(debounce); request?.abort(); });
</script>

<template>
  <div class="min-h-screen bg-background">
    <MenuBar />
    <main id="main-content" class="page-shell">
      <h1 class="page-heading mb-3">{{ $t(isSearch ? 'discovery.title' : 'watchlist.title') }}</h1>
      <p v-if="!isSearch" class="mb-8 max-w-2xl text-sm leading-6 text-muted">{{ $t('watchlist.description') }}</p>
      <search v-else><form class="mb-8 mt-6 flex max-w-3xl gap-3" @submit.prevent="changeQuery">
        <label for="catalogue-search" class="sr-only">{{ $t('discovery.searchLabel') }}</label>
        <input id="catalogue-search" ref="searchField" v-model="searchInput" type="search" name="q" maxlength="200" autocomplete="off" :placeholder="$t('discovery.placeholder')" class="field-input min-w-0 flex-1" />
        <button type="submit" class="button-primary">{{ $t('discovery.action') }}</button>
      </form></search>
      <p v-if="loading" role="status" class="empty-state">{{ $t('common.loading') }}</p>
      <div v-else-if="error" role="alert" class="empty-state"><p class="mb-5 text-red-200">{{ error }}</p><button type="button" class="button-secondary" @click="revision++">{{ $t('common.retry') }}</button></div>
      <div v-else-if="isSearch && !query" class="empty-state"><p>{{ $t('discovery.prompt') }}</p></div>
      <template v-else>
        <p v-if="items.length" role="status" class="mb-5 text-sm text-muted">{{ $t('library.pageInfo', {page, count:items.length}) }}</p>
        <div v-if="items.length" class="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7">
          <MediaCard v-for="item in items" :key="item.id" :media-file="item" :return-to="route.fullPath" />
        </div>
        <div v-else role="status" class="empty-state">
          <p>{{ isSearch ? $t('discovery.empty', {query}) : $t('watchlist.empty') }}</p>
          <RouterLink v-if="!isSearch" to="/" class="button-secondary mt-5">{{ $t('watchlist.browse') }}</RouterLink>
        </div>
        <nav v-if="page > 1 || hasNext" class="mt-10 flex items-center justify-between gap-4" :aria-label="$t('library.pagination')">
          <RouterLink v-if="page > 1" :to="destination(page - 1)" class="button-secondary">← {{ $t('common.previous') }}</RouterLink><span v-else></span>
          <RouterLink v-if="hasNext" :to="destination(page + 1)" class="button-secondary">{{ $t('common.next') }} →</RouterLink>
        </nav>
      </template>
    </main>
  </div>
</template>
