<script setup lang="ts">
import { onMounted, onUnmounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type HomepageRow, type ItemCard, items, libraries as libraryApi, type MediaCardInfo, watchlist } from "@/api/client";
import MediaRow from "../components/MediaRow.vue";
import MenuBar from "../components/MenuBar.vue";

const { t } = useI18n();

const rows: Ref<HomepageRow[]> = ref([]);
const watchlistItems = ref<MediaCardInfo[]>([]);
const continueWatchingItems=ref<ItemCard[]>([]);
const nextUpItems=ref<ItemCard[]>([]);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");
let request:AbortController|undefined;
let loaded=false;
onUnmounted(()=>request?.abort());

function getDisplayName(row: HomepageRow): string {
  // Use display_name from API (already processed - replaces {library_name} if present)
  // Handle special recommendation rows with internationalization
  // Check if it's a "Recently Added" row (name starts with "Recently Added")
  if (row.name.startsWith("Recently Added")) {
    // For special "Recently Added" rows, use i18n
    if (row.library_name && row.display_name.includes(row.library_name)) {
      return t("recommendationRows.recentlyAddedIn", { library_name: row.library_name });
    }
    return t("recommendationRows.recentlyAdded");
  }

  return row.display_name;
}

async function loadRows(): Promise<void> {
  request?.abort();
  const controller=new AbortController();request=controller;
  loading.value = !loaded;
  error.value = "";

  try {
    const [homepageRows, continueItems, savedItems,nextItems] = await Promise.all([
      libraryApi.getHomepageRows(controller.signal),
      items.resume(24,controller.signal),
      watchlist.list(0, 12,controller.signal).catch(() => []),
      items.nextUp(24,controller.signal),
    ]);
    controller.signal.throwIfAborted();
    loaded=true;
    rows.value = homepageRows;
    continueWatchingItems.value = continueItems;
    watchlistItems.value = savedItems;
    nextUpItems.value=nextItems;
  } catch (err) {
    if(controller.signal.aborted)return;
    console.error("Failed to load homepage rows:", err);
    error.value = t("home.loadFailed");
  } finally {
    if(!controller.signal.aborted) loading.value = false;
  }
}

onMounted(async () => {
  await loadRows();
});
</script>

<template>
  <div class="home-view min-h-screen bg-background">
    <MenuBar />

    <main id="main-content" class="page-shell">
      <h1 class="sr-only">{{ $t('common.homepage') }}</h1>
      <div v-if="loading" role="status" class="text-center text-gray-400 py-12">
        {{ $t('home.loadingMediaFiles') }}
      </div>

      <div v-else-if="error" role="alert" class="text-center py-12">
        <p class="text-red-400 mb-4">{{ error }}</p>
        <button
          type="button"
          @click="loadRows"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
        >
          {{ $t('common.retry') }}
        </button>
      </div>

      <div v-else>
        <div v-if="rows.length === 0 && continueWatchingItems.length === 0 && watchlistItems.length === 0 && nextUpItems.length===0" class="text-center text-gray-400 py-12">
          <p>{{ $t('home.noRows') }}</p>
        </div>
        <div v-else>
          <MediaRow hide-watch-actions
            v-if="continueWatchingItems.length > 0"
            :display-name="$t('home.continueWatching')"
            :items="continueWatchingItems" @changed="loadRows"
          />
          <MediaRow hide-watch-actions v-if="nextUpItems.length" :display-name="$t('items.nextUp')" :items="nextUpItems" @changed="loadRows" />
          <section v-if="watchlistItems.length" class="relative">
            <RouterLink to="/watchlist" class="mb-3 inline-block text-sm font-medium text-primary-300 hover:text-primary-200">{{ $t('watchlist.viewAll') }} →</RouterLink>
            <MediaRow hide-watch-actions :display-name="$t('watchlist.title')" :items="watchlistItems" @changed="loadRows" />
          </section>
          <MediaRow hide-watch-actions
            v-for="row in rows"
            :key="`${row.playlist_id}-${row.library_id}`"
            :display-name="getDisplayName(row)"
            :items="row.items"
            :source-library-id="row.library_id" @changed="loadRows"
          />
        </div>
      </div>
    </main>
  </div>
</template>
