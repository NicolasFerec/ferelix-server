<script setup lang="ts">
import { computed, onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type HomepageRow, libraries as libraryApi, type MediaCardInfo, media } from "@/api/client";
import FeaturedMedia from "@/components/FeaturedMedia.vue";
import MediaRow from "../components/MediaRow.vue";
import MenuBar from "../components/MenuBar.vue";

const { t } = useI18n();

const rows: Ref<HomepageRow[]> = ref([]);
const continueWatchingItems: Ref<MediaCardInfo[]> = ref([]);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");
const featured = computed(() => continueWatchingItems.value[0] || rows.value.flatMap(row => row.items)[0]);

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
    const [homepageRows, continueItems] = await Promise.all([
      libraryApi.getHomepageRows(),
      media.getContinueWatching(),
    ]);
    rows.value = homepageRows;
    continueWatchingItems.value = continueItems;
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
        <div v-if="rows.length === 0 && continueWatchingItems.length === 0" class="text-center text-gray-400 py-12">
          <p>{{ $t('home.noRows') }}</p>
        </div>
        <div v-else>
          <FeaturedMedia v-if="featured" :item="featured" />
          <MediaRow
            v-if="continueWatchingItems.length > 0"
            :display-name="$t('home.continueWatching')"
            :items="continueWatchingItems"
          />
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
