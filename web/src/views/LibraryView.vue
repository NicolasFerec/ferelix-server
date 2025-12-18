<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { libraries as libraryApi } from "@/api/client";
import MediaCard from "../components/MediaCard.vue";
import MediaRow from "../components/MediaRow.vue";
import MenuBar from "../components/MenuBar.vue";

const { t } = useI18n();
const route = useRoute();

const library = ref(null);
const rows = ref([]);
const items = ref([]);
const loading = ref(false);
const loadingItems = ref(false);
const error = ref("");
const activeTab = ref("recommended");

function getDisplayName(row) {
  // Use display_name from API (already processed - replaces {library_name} if present)
  // Handle special recommendation rows with internationalization
  // Check if it's a "Recently Added" row (name starts with "Recently Added")
  if (row.name.startsWith("Recently Added")) {
    // For special "Recently Added" rows, use i18n
    if (row.display_name.includes(row.library_name)) {
      return t("recommendationRows.recentlyAddedIn", { library_name: row.library_name });
    }
    return t("recommendationRows.recentlyAdded");
  }

  return row.display_name;
}

async function loadLibrary() {
  const routeId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id;
  const libraryId = parseInt(routeId, 10);
  if (!libraryId) {
    error.value = "Invalid library ID";
    return;
  }

  try {
    const libraries = await libraryApi.getLibraries();
    library.value = libraries.find((lib) => lib.id === libraryId);
    if (!library.value) {
      error.value = "Library not found";
    }
  } catch (err) {
    console.error("Failed to load library:", err);
    error.value = "Failed to load library";
  }
}

async function loadRows() {
  const routeId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id;
  const libraryId = parseInt(routeId, 10);
  if (!libraryId) return;

  try {
    rows.value = await libraryApi.getLibraryRows(libraryId);
  } catch (err) {
    console.error("Failed to load library rows:", err);
    // Don't set error for rows, just show empty state
  }
}

async function loadItems() {
  const routeId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id;
  const libraryId = parseInt(routeId, 10);
  if (!libraryId) return;

  loadingItems.value = true;
  try {
    items.value = await libraryApi.getLibraryItems(libraryId);
  } catch (err) {
    console.error("Failed to load library items:", err);
    items.value = [];
  } finally {
    loadingItems.value = false;
  }
}

async function loadData() {
  loading.value = true;
  error.value = "";

  try {
    await loadLibrary();
    if (library.value) {
      await Promise.all([loadRows(), loadItems()]);
    }
  } catch (err) {
    console.error("Failed to load data:", err);
    error.value = "Failed to load data";
  } finally {
    loading.value = false;
  }
}

// Watch for tab changes to load items if needed
watch(activeTab, (newTab) => {
  if (newTab === "library" && items.value.length === 0 && !loadingItems.value) {
    loadItems();
  }
});

onMounted(async () => {
  await loadData();
});
</script>

<template>
  <div class="library-view min-h-screen bg-gray-900">
    <MenuBar />

    <main class="container mx-auto px-6 pt-4 pb-8">
      <div v-if="loading" class="text-center text-gray-400 py-12">
        {{ $t('common.loading') }}
      </div>

      <div v-else-if="error" class="text-center py-12">
        <p class="text-red-400 mb-4">{{ error }}</p>
        <button
          @click="loadData"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
        >
          {{ $t('common.retry') }}
        </button>
      </div>

      <div v-else>
        <!-- Tabs -->
        <div class="border-b border-gray-700 mb-6">
          <nav class="-mb-px flex space-x-8">
            <button
              @click="activeTab = 'recommended'"
              :class="[
                'py-4 px-1 border-b-2 font-medium text-sm transition-colors',
                activeTab === 'recommended'
                  ? 'border-primary-500 text-primary-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300',
              ]"
            >
              {{ $t('library.recommended') }}
            </button>
            <button
              @click="activeTab = 'library'"
              :class="[
                'py-4 px-1 border-b-2 font-medium text-sm transition-colors',
                activeTab === 'library'
                  ? 'border-primary-500 text-primary-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300 hover:border-gray-300',
              ]"
            >
              {{ $t('library.allItems') }}
            </button>
          </nav>
        </div>

        <!-- Recommended Tab -->
        <div v-if="activeTab === 'recommended'">
          <div v-if="rows.length === 0" class="text-center text-gray-400 py-12">
            <p>{{ $t('home.noRows') }}</p>
          </div>
          <div v-else class="-mx-6">
            <MediaRow
              v-for="row in rows"
              :key="`${row.playlist_id}-${row.library_id}`"
              :displayName="getDisplayName(row)"
              :items="row.items"
            />
          </div>
        </div>

        <!-- Library Tab -->
        <div v-if="activeTab === 'library'">
          <div v-if="loadingItems" class="text-center text-gray-400 py-12">
            {{ $t('common.loading') }}
          </div>
          <div v-else-if="items.length === 0" class="text-center text-gray-400 py-12">
            <p>{{ $t('home.noItems') }}</p>
          </div>
          <div
            v-else
            class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
          >
            <MediaCard v-for="item in items" :key="item.id" :mediaFile="item" />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
