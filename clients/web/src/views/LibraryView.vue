<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { type HomepageRow, type Library, libraries, type MediaCardInfo } from "@/api/client";
import MediaCard from "@/components/MediaCard.vue";
import MediaRow from "@/components/MediaRow.vue";
import MenuBar from "@/components/MenuBar.vue";

const { t } = useI18n();
const route = useRoute();
const pageSize = 48;
const library = ref<Library | null>(null);
const rows = ref<HomepageRow[]>([]);
const items = ref<MediaCardInfo[]>([]);
const loading = ref(true);
const error = ref("");
const hasNext = ref(false);
const revision = ref(0);
const libraryId = computed(() => Number(route.params.id));
const activeTab = computed(() => route.query.tab === "library" ? "library" : "recommended");
const page = computed(() => Math.max(1, Math.min(1000000, Math.floor(Number(route.query.page) || 1))));
function destination(tab: string, targetPage = 1) {
  return { query: { ...route.query, tab, page: tab === "library" ? String(targetPage) : undefined } };
}
function displayName(row: HomepageRow) {
  return row.name.startsWith("Recently Added") ? t("recommendationRows.recentlyAdded") : row.display_name;
}

watch(() => [libraryId.value, activeTab.value, page.value, revision.value], async (_, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  loading.value = true;
  error.value = "";
  try {
    if (!Number.isSafeInteger(libraryId.value) || libraryId.value <= 0) throw new Error(t("library.invalidId"));
    if (library.value?.id !== libraryId.value) {
      const id = libraryId.value;
      const availableLibraries = await libraries.getLibraries();
      controller.signal.throwIfAborted();
      library.value = availableLibraries.find(item => item.id === id) || null;
    }
    if (!library.value) throw new Error(t("library.notFound"));
    if (activeTab.value === "recommended") {
      const response = await libraries.getLibraryRows(libraryId.value, controller.signal);
      controller.signal.throwIfAborted();
      rows.value = response;
    } else {
      // One look-ahead card tells us whether another page exists; no full-library crawl.
      const response = await libraries.getLibraryItems(libraryId.value, (page.value - 1) * pageSize, pageSize + 1, controller.signal);
      controller.signal.throwIfAborted();
      hasNext.value = response.length > pageSize;
      items.value = response.slice(0, pageSize);
    }
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause instanceof Error ? cause.message : t("library.loadFailed");
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}, { immediate: true });
</script>

<template>
  <div class="min-h-screen bg-background">
    <MenuBar />
    <main id="main-content" class="page-shell">
      <div class="mb-8">
        <p class="mb-2 text-xs font-semibold uppercase tracking-[.2em] text-primary-300">{{ $t('common.library') }}</p>
        <h1 class="page-heading">{{ library?.name || $t('library.title') }}</h1>
      </div>
      <nav class="mb-8 flex gap-2 border-b border-outline pb-4" :aria-label="$t('library.title')">
        <RouterLink :to="destination('recommended')" class="rounded-xl px-4 py-2.5 text-sm font-medium" :class="activeTab === 'recommended' ? 'bg-white/10 text-white' : 'text-muted hover:text-white'" :aria-current="activeTab === 'recommended' ? 'page' : undefined">{{ $t('library.recommended') }}</RouterLink>
        <RouterLink :to="destination('library')" class="rounded-xl px-4 py-2.5 text-sm font-medium" :class="activeTab === 'library' ? 'bg-white/10 text-white' : 'text-muted hover:text-white'" :aria-current="activeTab === 'library' ? 'page' : undefined">{{ $t('library.allItems') }}</RouterLink>
      </nav>
      <p v-if="loading" role="status" class="empty-state">{{ $t('common.loading') }}</p>
      <div v-else-if="error" role="alert" class="empty-state"><p class="mb-5 text-red-200">{{ error }}</p><button type="button" class="button-secondary" @click="revision++">{{ $t('common.retry') }}</button></div>
      <template v-else-if="activeTab === 'recommended'">
        <p v-if="!rows.length" class="empty-state">{{ $t('home.noRows') }}</p>
        <MediaRow v-for="row in rows" :key="`${row.playlist_id}-${row.library_id}`" :display-name="displayName(row)" :items="row.items" :source-library-id="libraryId" />
      </template>
      <template v-else>
        <p class="mb-5 text-sm text-muted" role="status">{{ $t('library.pageInfo', { page, count: items.length }) }}</p>
        <div v-if="items.length" class="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7">
          <MediaCard v-for="item in items" :key="item.id" :media-file="item" :source-library-id="libraryId" />
        </div>
        <p v-else class="empty-state">{{ $t('home.noItems') }}</p>
        <nav v-if="page > 1 || hasNext" class="mt-10 flex items-center justify-between gap-4" :aria-label="$t('library.pagination')">
          <RouterLink v-if="page > 1" :to="destination('library', page - 1)" class="button-secondary">← {{ $t('common.previous') }}</RouterLink><span v-else></span>
          <RouterLink v-if="hasNext" :to="destination('library', page + 1)" class="button-secondary">{{ $t('common.next') }} →</RouterLink>
        </nav>
      </template>
    </main>
  </div>
</template>
