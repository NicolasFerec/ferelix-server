<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type Library, libraries as libraryApi } from "@/api/client";
import LibraryForm from "./LibraryForm.vue";
import LibraryItem from "./LibraryItem.vue";

const { t } = useI18n();

const libraries = ref<Library[]>([]);
const loading = ref(false);
const error = ref("");
const showForm = ref(false);
const editingLibrary = ref<Library | null>(null);

async function loadLibraries() {
  loading.value = true;
  error.value = "";
  try {
    // Use getAllLibraries() for admin management (includes all libraries, not just enabled)
    libraries.value = await libraryApi.getAllLibraries();
  } catch (err: unknown) {
    console.error("Failed to load libraries:", err);
    const apiErr = err as { data?: { detail?: string } };
    error.value = apiErr.data?.detail || t("libraries.loadFailed");
  } finally {
    loading.value = false;
  }
}

function handleEdit(library: Library) {
  editingLibrary.value = library;
  showForm.value = true;
}

async function handleDelete(library: Library) {
  if (!confirm(t("libraries.confirmDelete"))) {
    return;
  }

  try {
    await libraryApi.deleteLibrary(library.id);
    await loadLibraries();
  } catch (err: unknown) {
    console.error("Failed to delete library:", err);
    const apiErr = err as { data?: { detail?: string } };
    alert(apiErr.data?.detail || t("libraries.deleteFailed"));
  }
}

function handleScan(_library: Library) {
  // Show success message - scan is async, user can check Jobs panel for progress
  alert(t("libraries.scanStarted"));
}

function handleSaved() {
  showForm.value = false;
  editingLibrary.value = null;
  loadLibraries();
}

onMounted(() => {
  loadLibraries();
});
</script>

<template>
  <div class="library-list">
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-semibold text-white">{{ $t('libraries.title') }}</h2>
      <button
        @click="
          showForm = true;
          editingLibrary = null;
        "
        class="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-md transition-colors"
      >
        {{ $t('libraries.add') }}
      </button>
    </div>

    <!-- Library Form Modal -->
    <LibraryForm
      v-if="showForm"
      :library="editingLibrary"
      @close="
        showForm = false;
        editingLibrary = null;
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
        @click="loadLibraries"
        class="mt-4 px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ $t('common.retry') }}
      </button>
    </div>

    <!-- Empty state -->
    <div v-else-if="libraries.length === 0" class="text-center text-gray-400 py-12">
      <p>{{ $t('libraries.noLibraries') }}</p>
    </div>

    <!-- Libraries table -->
    <div v-else class="bg-gray-800 rounded-lg overflow-visible">
      <table class="min-w-full divide-y divide-gray-700">
        <thead class="bg-gray-700">
          <tr>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider rounded-tl-lg"
            >
              {{ $t('libraries.name') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('libraries.path') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('libraries.typeLabel') }}
            </th>
            <th
              class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              {{ $t('libraries.enabled') }}
            </th>
            <th
              class="px-6 py-3 text-right text-xs font-medium text-gray-300 uppercase tracking-wider rounded-tr-lg"
            >
              {{ $t('common.actions') }}
            </th>
          </tr>
        </thead>
        <tbody class="bg-gray-800 divide-y divide-gray-700">
          <LibraryItem
            v-for="library in libraries"
            :key="library.id"
            :library="library"
            @edit="handleEdit"
            @delete="handleDelete"
            @scan="handleScan"
          />
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.library-list tbody tr:last-child td:first-child {
  border-bottom-left-radius: 0.5rem;
}

.library-list tbody tr:last-child td:last-child {
  border-bottom-right-radius: 0.5rem;
}
</style>
