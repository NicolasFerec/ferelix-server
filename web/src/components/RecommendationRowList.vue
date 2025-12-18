<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi, recommendationRows as rowApi } from "@/api/client";
import RecommendationRowForm from "./RecommendationRowForm.vue";
import RecommendationRowItem from "./RecommendationRowItem.vue";

const { t } = useI18n();

const rows = ref([]);
const libraries = ref([]);
const loading = ref(false);
const error = ref("");
const showForm = ref(false);
const editingRow = ref(null);

async function loadLibraries() {
  try {
    libraries.value = await libraryApi.getAllLibraries();
  } catch (err) {
    console.error("Failed to load libraries:", err);
  }
}

async function loadRows() {
  loading.value = true;
  error.value = "";
  try {
    rows.value = await rowApi.getRows();
    // Load library names for display
    await loadLibraries();
    // Enrich rows with library names
    rows.value = rows.value.map((row) => {
      const library = libraries.value.find((lib) => lib.id === row.library_id);
      return {
        ...row,
        library_name: library?.name || "Unknown",
      };
    });
  } catch (err) {
    console.error("Failed to load recommendation rows:", err);
    error.value = err.data?.detail || t("recommendationRows.loadFailed");
  } finally {
    loading.value = false;
  }
}

function handleEdit(row) {
  editingRow.value = row;
  showForm.value = true;
}

async function handleDelete(row) {
  if (row.is_special) {
    alert(t("recommendationRows.cannotDeleteSpecial"));
    return;
  }

  if (!confirm(t("recommendationRows.confirmDelete"))) {
    return;
  }

  try {
    await rowApi.deleteRow(row.id);
    await loadRows();
  } catch (err) {
    console.error("Failed to delete recommendation row:", err);
    alert(err.data?.detail || t("recommendationRows.deleteFailed"));
  }
}

function handleSaved() {
  showForm.value = false;
  editingRow.value = null;
  loadRows();
}

onMounted(() => {
  loadRows();
});
</script>

<template>
  <div class="recommendation-row-list">
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-semibold text-white">{{ $t('recommendationRows.title') }}</h2>
      <button
        @click="
          showForm = true;
          editingRow = null;
        "
        class="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-md transition-colors"
      >
        {{ $t('recommendationRows.add') }}
      </button>
    </div>

    <!-- Recommendation Row Form Modal -->
    <RecommendationRowForm
      v-if="showForm"
      :row="editingRow"
      @close="
        showForm = false;
        editingRow = null;
      "
      @saved="handleSaved"
    />

    <!-- Loading state -->
    <div v-if="loading" class="text-center text-gray-400 py-12">
      {{ $t('common.loading') }}
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="text-center text-red-400 py-12">
      <p>{{ error }}</p>
      <button
        @click="loadRows"
        class="mt-4 px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ $t('common.retry') }}
      </button>
    </div>

    <!-- Empty state -->
    <div v-else-if="rows.length === 0" class="text-center text-gray-400 py-12">
      <p>{{ $t('recommendationRows.noRows') }}</p>
    </div>

    <!-- Recommendation Rows table -->
    <div v-else class="bg-gray-800 rounded-lg overflow-visible">
      <table class="min-w-full divide-y divide-gray-700">
        <thead class="bg-gray-700">
          <tr>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider rounded-tl-lg"
            >
              {{ $t('recommendationRows.name') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('libraries.name') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('recommendationRows.visibleOnHomepage') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('recommendationRows.visibleOnRecommend') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('recommendationRows.special') }}
            </th>
            <th
              class="px-6 py-3 text-right text-xs font-medium text-gray-300 uppercase tracking-wider rounded-tr-lg"
            >
              {{ $t('common.actions') }}
            </th>
          </tr>
        </thead>
        <tbody class="bg-gray-800 divide-y divide-gray-700">
          <RecommendationRowItem
            v-for="row in rows"
            :key="row.id"
            :row="row"
            @edit="handleEdit"
            @delete="handleDelete"
          />
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.recommendation-row-list tbody tr:last-child td:first-child {
  border-bottom-left-radius: 0.5rem;
}

.recommendation-row-list tbody tr:last-child td:last-child {
  border-bottom-right-radius: 0.5rem;
}
</style>
