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
import { useToast } from "@/composables/useToast";
import DashboardTable from "./DashboardTable.vue";
import RecommendationRowForm from "./RecommendationRowForm.vue";

const props = defineProps<{
  library: Library;
}>();

const emit = defineEmits(["edit", "delete", "scan"]);

const { t } = useI18n();
const toast = useToast();

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
    toast.error(apiErr.data?.detail || t("recommendationRows.loadFailed"));
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
    toast.error(apiErr.data?.detail || t("recommendationRows.updateFailed"));
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
    toast.warn(t("recommendationRows.cannotDeleteSpecial"));
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
    toast.error(apiErr.data?.detail || t("recommendationRows.deleteFailed"));
  }
}

function handleRowSaved() {
  toast.success(editingRow.value ? t("recommendationRows.updateSuccess") : t("recommendationRows.createSuccess"));
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
    toast.error(apiErr.data?.detail || t("libraries.scanFailed"));
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
  <tr class="transition-colors hover:bg-primary-900/20">
    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
      <div class="flex items-center gap-2">
        <button
          @click="handleManageRecommendations"
          class="rounded-sm p-1 text-gray-400 transition-colors hover:bg-gray-600 hover:text-white"
          :title="expanded ? $t('libraries.collapse') : $t('libraries.expand')"
          :aria-expanded="expanded"
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
        <span class="group relative inline-flex">
          <button
            @click="handleScan"
            :disabled="scanning"
            class="rounded-md border border-gray-600 bg-gray-700 p-2 text-gray-300 transition-colors hover:border-primary-500 hover:bg-gray-600 hover:text-white disabled:opacity-50 disabled:cursor-not-allowed"
            :aria-label="$t('libraries.actions.scan')"
            :title="$t('libraries.actions.scan')"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </button>
          <span
            class="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-950 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
          >
            {{ $t('libraries.actions.scan') }}
          </span>
        </span>
        <span class="group relative inline-flex">
          <button
            @click="handleEdit"
            class="rounded-md border border-gray-600 bg-gray-700 p-2 text-gray-300 transition-colors hover:border-primary-500 hover:bg-gray-600 hover:text-white"
            :aria-label="$t('libraries.actions.edit')"
            :title="$t('libraries.actions.edit')"
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
          <span
            class="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-950 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
          >
            {{ $t('libraries.actions.edit') }}
          </span>
        </span>
        <span class="group relative inline-flex">
          <button
            @click="handleManageRecommendations"
            class="rounded-md border border-primary-800 bg-primary-900/50 p-2 text-primary-300 transition-colors hover:border-primary-500 hover:bg-primary-900/70 hover:text-primary-100"
            :aria-label="$t('libraries.manageRecommendations')"
            :title="$t('libraries.manageRecommendations')"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M4 6h16M4 12h10M4 18h7m8-5l1.5 1.5L22 13m-5 5l1.5 1.5L22 18"
              />
            </svg>
          </button>
          <span
            class="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-950 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
          >
            {{ $t('libraries.manageRecommendations') }}
          </span>
        </span>
        <span class="group relative inline-flex">
          <button
            @click="handleDelete"
            class="rounded-md border border-red-900/70 bg-red-900/30 p-2 text-red-400 transition-colors hover:border-red-700 hover:bg-red-900/50 hover:text-red-300"
            :aria-label="$t('libraries.actions.delete')"
            :title="$t('libraries.actions.delete')"
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
          <span
            class="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-950 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100"
          >
            {{ $t('libraries.actions.delete') }}
          </span>
        </span>
      </div>
    </td>
  </tr>

  <!-- Expanded recommendation rows section (appears below the library row) -->
  <tr v-if="expanded" class="bg-gray-750">
    <td colspan="5" class="px-6 py-5">
      <div class="space-y-4 rounded-lg border border-gray-700 bg-gray-800/70 p-4">
        <!-- Recommendation rows header -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-white">
              {{ $t('libraries.recommendationRows') }}
            </h3>
          </div>
          <button
            @click="handleAddRow"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors"
          >
            {{ $t('recommendationRows.add') }}
          </button>
        </div>

        <!-- Recommendation rows list -->
        <div v-if="loadingRows" class="rounded-lg border border-gray-700 bg-gray-800 px-4 py-8 text-center text-gray-400">
          {{ $t('common.loading') }}
        </div>
        <div
          v-else-if="rows.length === 0"
          class="rounded-lg border border-gray-700 bg-gray-800 px-4 py-8 text-center text-gray-400"
        >
          {{ $t('recommendationRows.noRows') }}
        </div>
        <DashboardTable v-else class="border border-gray-700" table-class="w-full table-fixed divide-y divide-gray-700">
          <colgroup>
            <col class="w-[42%]" />
            <col class="w-[25%]" />
            <col class="w-[23%]" />
            <col class="w-[10%]" />
          </colgroup>
          <thead class="bg-gray-700/80">
              <tr>
                <th
                  class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-300"
                >
                  {{ $t('recommendationRows.name') }}
                </th>
                <th
                  class="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-300"
                >
                  {{ $t('recommendationRows.visibleOnHomepage') }}
                </th>
                <th
                  class="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-300"
                >
                  {{ $t('recommendationRows.visibleOnRecommend') }}
                </th>
                <th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-300">
                  {{ $t('common.actions') }}
                </th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-700">
              <tr
                v-for="row in rows"
                :key="row.id"
                class="transition-colors hover:bg-primary-900/10"
              >
                <td class="px-4 py-3">
                  <div class="flex min-w-64 items-center gap-2">
                    <span class="text-sm font-medium text-white">{{ getDisplayName(row) }}</span>
                    <span
                      v-if="row.is_special"
                      class="whitespace-nowrap rounded-full bg-primary-900/50 px-2 py-0.5 text-xs font-medium text-primary-200"
                    >
                      {{ $t('recommendationRows.special') }}
                    </span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <label
                    class="mx-auto flex w-max items-center justify-center"
                    :class="{ 'cursor-wait opacity-70': updatingVisibility === row.id }"
                  >
                    <span class="sr-only">{{ $t('recommendationRows.visibleOnHomepage') }}</span>
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
                      class="peer sr-only"
                    />
                    <span
                      class="relative h-6 w-11 rounded-full bg-gray-600 transition-colors after:absolute after:left-1 after:top-1 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:bg-primary-600 peer-checked:after:translate-x-5 peer-disabled:opacity-50"
                    ></span>
                  </label>
                </td>
                <td class="px-4 py-3">
                  <label
                    class="mx-auto flex w-max items-center justify-center"
                    :class="{ 'cursor-wait opacity-70': updatingVisibility === row.id }"
                  >
                    <span class="sr-only">{{ $t('recommendationRows.visibleOnRecommend') }}</span>
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
                      class="peer sr-only"
                    />
                    <span
                      class="relative h-6 w-11 rounded-full bg-gray-600 transition-colors after:absolute after:left-1 after:top-1 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:bg-primary-600 peer-checked:after:translate-x-5 peer-disabled:opacity-50"
                    ></span>
                  </label>
                </td>
                <td class="px-4 py-3">
                  <div class="flex justify-end gap-2">
                    <button
                      @click="handleEditRow(row)"
                      class="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white"
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
                      class="rounded-md p-2 text-gray-400 transition-colors hover:bg-red-900/30 hover:text-red-400 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
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
                </td>
              </tr>
            </tbody>
        </DashboardTable>
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
