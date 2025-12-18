<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  type Library,
  libraries as libraryApi,
  type RecommendationRow,
  type RecommendationRowUpdate,
  recommendationRows as rowApi,
} from "@/api/client";
import RecommendationRowForm from "./RecommendationRowForm.vue";

const props = defineProps<{
  library: Library;
}>();

const emit = defineEmits(["edit", "delete", "scan"]);

const { t } = useI18n();

const expanded = ref(false);
const scanning = ref(false);
const rows = ref<RecommendationRow[]>([]);
const loadingRows = ref(false);
const updatingVisibility = ref<number | null>(null);
const showRowForm = ref(false);
const editingRow = ref<RecommendationRow | null>(null);

function getLibraryTypeLabel(type: string) {
  if (type === "movie") {
    return t("libraries.type.movie");
  } else if (type === "tv_show") {
    return t("libraries.type.tv_show");
  }
  return type;
}

function getDisplayName(row: RecommendationRow) {
  // Replace %LIBRARY_NAME% placeholder with actual library name
  let displayName = row.name;
  if (displayName.includes("%LIBRARY_NAME%")) {
    displayName = displayName.replace("%LIBRARY_NAME%", props.library.name);
  } else if (displayName.includes("{library_name}")) {
    // Backward compatibility with old format
    displayName = displayName.replace("{library_name}", props.library.name);
  }

  // Handle special recommendation rows with internationalization
  // Check if it's a "Recently Added" row (name starts with "Recently Added")
  if (row.name.startsWith("Recently Added")) {
    // For special "Recently Added" rows, use i18n
    if (displayName.includes(props.library.name)) {
      return t("recommendationRows.recentlyAddedIn", { library_name: props.library.name });
    }
    return t("recommendationRows.recentlyAdded");
  }

  return displayName;
}

async function loadRecommendationRows() {
  loadingRows.value = true;
  try {
    rows.value = await rowApi.getLibraryRows(props.library.id);
  } catch (err: unknown) {
    console.error("Failed to load recommendation rows:", err);
    const apiErr = err as { data?: { detail?: string } };
    alert(apiErr.data?.detail || t("recommendationRows.loadFailed"));
  } finally {
    loadingRows.value = false;
  }
}

function handleManageRecommendations() {
  expanded.value = !expanded.value;
  if (expanded.value) {
    loadRecommendationRows();
  }
}

async function handleToggleVisibility(row: RecommendationRow, type: string, checked: boolean) {
  updatingVisibility.value = row.id ?? null;
  try {
    const updateData: RecommendationRowUpdate = {};
    if (type === "recommend") {
      updateData.visible_on_recommend = checked;
    } else {
      updateData.visible_on_homepage = checked;
    }

    await rowApi.updateLibraryRow(props.library.id, row.id, updateData);

    // Update local state
    if (type === "recommend") {
      row.visible_on_recommend = checked;
    } else {
      row.visible_on_homepage = checked;
    }
  } catch (err: unknown) {
    console.error("Failed to update visibility:", err);
    const apiErr = err as { data?: { detail?: string } };
    alert(apiErr.data?.detail || t("recommendationRows.updateFailed"));
  } finally {
    updatingVisibility.value = null;
  }
}

function handleAddRow() {
  editingRow.value = null;
  showRowForm.value = true;
}

function handleEditRow(row: RecommendationRow) {
  editingRow.value = row;
  showRowForm.value = true;
}

async function handleDeleteRow(row: RecommendationRow) {
  if (row.is_special) {
    alert(t("recommendationRows.cannotDeleteSpecial"));
    return;
  }

  if (!confirm(t("recommendationRows.confirmDelete"))) {
    return;
  }

  try {
    await rowApi.removeLibraryRow(props.library.id, row.id);
    await loadRecommendationRows();
  } catch (err: unknown) {
    console.error("Failed to delete recommendation row:", err);
    const apiErr = err as { data?: { detail?: string } };
    alert(apiErr.data?.detail || t("recommendationRows.deleteFailed"));
  }
}

function handleRowSaved() {
  showRowForm.value = false;
  editingRow.value = null;
  loadRecommendationRows();
}

async function handleScan() {
  scanning.value = true;

  try {
    await libraryApi.scanLibrary(props.library.id);
    emit("scan", props.library);
  } catch (err: unknown) {
    console.error("Failed to scan library:", err);
    const apiErr = err as { data?: { detail?: string } };
    alert(apiErr.data?.detail || t("libraries.scanFailed"));
  } finally {
    scanning.value = false;
  }
}

function handleEdit() {
  emit("edit", props.library);
}

function handleDelete() {
  emit("delete", props.library);
}

onMounted(() => {
  // No longer needed - removed dropdown
});

onBeforeUnmount(() => {
  // No longer needed - removed dropdown
});
</script>

<template>
  <!-- Library row (always visible) -->
  <tr class="hover:bg-gray-700">
    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
      <div class="flex items-center gap-2">
        <button
          @click="handleManageRecommendations"
          class="text-gray-400 hover:text-white transition-colors"
          :title="expanded ? $t('libraries.collapse') : $t('libraries.expand')"
        >
          <svg
            class="w-4 h-4 transition-transform"
            :class="{ 'rotate-180': expanded }"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </button>
        {{ library.name }}
      </div>
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
      {{ library.path }}
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
      {{ getLibraryTypeLabel(library.library_type) }}
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm">
      <span
        :class="[
          'px-2 py-1 rounded-full text-xs font-medium',
          library.enabled ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400',
        ]"
      >
        {{ library.enabled ? $t('common.enabled') : $t('common.disabled') }}
      </span>
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
      <div class="flex items-center justify-end gap-2">
        <button
          @click="handleScan"
          :disabled="scanning"
          class="px-3 py-1 text-xs font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ $t('libraries.actions.scan') }}
        </button>
        <button
          @click="handleEdit"
          class="px-3 py-1 text-xs font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors"
        >
          {{ $t('libraries.actions.edit') }}
        </button>
        <button
          @click="handleManageRecommendations"
          class="px-3 py-1 text-xs font-medium text-primary-300 bg-primary-900/50 hover:bg-primary-900/70 rounded-md transition-colors"
        >
          {{ $t('libraries.manageRecommendations') }}
        </button>
        <button
          @click="handleDelete"
          class="px-3 py-1 text-xs font-medium text-red-400 bg-red-900/30 hover:bg-red-900/50 rounded-md transition-colors"
        >
          {{ $t('libraries.actions.delete') }}
        </button>
      </div>
    </td>
  </tr>

  <!-- Expanded recommendation rows section (appears below the library row) -->
  <tr v-if="expanded" class="bg-gray-750">
    <td colspan="5" class="px-6 py-4">
      <div class="space-y-4">
        <!-- Recommendation rows header -->
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-white">{{ $t('libraries.recommendationRows') }}</h3>
        </div>

        <!-- Recommendation rows list -->
        <div class="bg-gray-800 rounded-lg overflow-hidden">
          <div class="px-4 py-3 bg-gray-700 border-b border-gray-600">
            <div
              class="grid grid-cols-12 gap-4 text-xs font-medium text-gray-300 uppercase tracking-wider"
            >
              <div class="col-span-5">{{ $t('recommendationRows.name') }}</div>
              <div class="col-span-3 text-center">
                {{ $t('recommendationRows.visibleOnHomepage') }}
              </div>
              <div class="col-span-3 text-center">
                {{ $t('recommendationRows.visibleOnRecommend') }}
              </div>
              <div class="col-span-1"></div>
            </div>
          </div>
          <div v-if="loadingRows" class="px-4 py-8 text-center text-gray-400">
            {{ $t('common.loading') }}
          </div>
          <div v-else-if="rows.length === 0" class="px-4 py-8 text-center text-gray-400">
            {{ $t('recommendationRows.noRows') }}
          </div>
          <div v-else class="divide-y divide-gray-700">
            <div
              v-for="row in rows"
              :key="row.id"
              class="px-4 py-3 hover:bg-gray-750 transition-colors"
            >
              <div class="grid grid-cols-12 gap-4 items-center">
                <div class="col-span-5 text-sm text-white font-medium">
                  {{ getDisplayName(row) }}
                </div>
                <div class="col-span-3 flex justify-center">
                  <input
                    type="checkbox"
                    :checked="row.visible_on_homepage"
                    @change="
                      handleToggleVisibility(
                        row,
                        'homepage',
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                    :disabled="updatingVisibility === row.id"
                    class="w-4 h-4 text-primary-600 bg-gray-700 border-gray-600 rounded-sm focus:ring-primary-500 disabled:opacity-50"
                  />
                </div>
                <div class="col-span-3 flex justify-center">
                  <input
                    type="checkbox"
                    :checked="row.visible_on_recommend"
                    @change="
                      handleToggleVisibility(
                        row,
                        'recommend',
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                    :disabled="updatingVisibility === row.id"
                    class="w-4 h-4 text-primary-600 bg-gray-700 border-gray-600 rounded-sm focus:ring-primary-500 disabled:opacity-50"
                  />
                </div>
                <div class="col-span-1 flex justify-end gap-2">
                  <button
                    @click="handleEditRow(row)"
                    class="p-1 text-gray-400 hover:text-white transition-colors"
                    :title="$t('common.edit')"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                      />
                    </svg>
                  </button>
                  <button
                    @click="handleDeleteRow(row)"
                    :disabled="row.is_special"
                    class="p-1 text-gray-400 hover:text-red-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    :title="$t('common.delete')"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                      />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="px-4 py-3 bg-gray-700 border-t border-gray-600">
            <button
              @click="handleAddRow"
              class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors"
            >
              {{ $t('recommendationRows.add') }}
            </button>
          </div>
        </div>
      </div>
    </td>
  </tr>

  <!-- Recommendation Row Form Modal -->
  <RecommendationRowForm
    v-if="showRowForm"
    :row="editingRow"
    :library-id="library.id"
    @close="
      showRowForm = false;
      editingRow = null;
    "
    @saved="handleRowSaved"
  />
</template>

<style scoped>
.bg-gray-750 {
  background-color: rgb(31, 41, 55);
}
</style>
