<script setup lang="ts">
import { onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type HomepageRow, libraries as libraryApi } from "@/api/client";
import MediaRow from "../components/MediaRow.vue";
import MenuBar from "../components/MenuBar.vue";

const { t } = useI18n();

const rows: Ref<HomepageRow[]> = ref([]);
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
    rows.value = await libraryApi.getHomepageRows();
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
  <div class="home-view min-h-screen bg-gray-900">
    <MenuBar />

    <main class="container mx-auto py-8">
      <div v-if="loading" class="text-center text-gray-400 py-12">
        {{ $t('home.loadingMediaFiles') }}
      </div>

      <div v-else-if="error" class="text-center py-12">
        <p class="text-red-400 mb-4">{{ error }}</p>
        <button
          @click="loadRows"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
        >
          {{ $t('common.retry') }}
        </button>
      </div>

      <div v-else>
        <div v-if="rows.length === 0" class="text-center text-gray-400 py-12">
          <p>{{ $t('home.noRows') }}</p>
        </div>
        <div v-else>
          <MediaRow
            v-for="row in rows"
            :key="`${row.playlist_id}-${row.library_id}`"
            :displayName="getDisplayName(row)"
            :items="row.items"
          />
        </div>
      </div>
    </main>
  </div>
</template>
