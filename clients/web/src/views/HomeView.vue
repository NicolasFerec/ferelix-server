<script setup lang="ts">
import { onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type HomepageRow, libraries as libraryApi, type MediaCardInfo, media, watchlist } from "@/api/client";
import MediaRow from "../components/MediaRow.vue";
import MenuBar from "../components/MenuBar.vue";

const { t } = useI18n();

const rows: Ref<HomepageRow[]> = ref([]);
const watchlistItems = ref<MediaCardInfo[]>([]);
const continueWatchingItems: Ref<MediaCardInfo[]> = ref([]);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");

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
  loading.value = true;
  error.value = "";

  try {
    const [homepageRows, continueItems, savedItems] = await Promise.all([
      libraryApi.getHomepageRows(),
      media.getContinueWatching(),
      watchlist.list(0, 12).catch(() => []),
    ]);
    rows.value = homepageRows;
    continueWatchingItems.value = continueItems;
    watchlistItems.value = savedItems;
  } catch (err) {
    console.error("Failed to load homepage rows:", err);
    error.value = t("home.loadFailed");
  } finally {
    loading.value = false;
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
        <div v-if="rows.length === 0 && continueWatchingItems.length === 0 && watchlistItems.length === 0" class="text-center text-gray-400 py-12">
          <p>{{ $t('home.noRows') }}</p>
        </div>
        <div v-else>
          <MediaRow
            v-if="continueWatchingItems.length > 0"
            :display-name="$t('home.continueWatching')"
            :items="continueWatchingItems"
          />
          <section v-if="watchlistItems.length" class="relative">
            <RouterLink to="/watchlist" class="mb-3 inline-block text-sm font-medium text-primary-300 hover:text-primary-200">{{ $t('watchlist.viewAll') }} →</RouterLink>
            <MediaRow :display-name="$t('watchlist.title')" :items="watchlistItems" />
          </section>
          <MediaRow
            v-for="row in rows"
            :key="`${row.playlist_id}-${row.library_id}`"
            :display-name="getDisplayName(row)"
            :items="row.items"
            :source-library-id="row.library_id"
          />
        </div>
      </div>
    </main>
  </div>
</template>
