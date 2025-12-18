<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi, recommendationRows as rowApi } from "@/api/client";

const props = defineProps({
  row: {
    type: Object,
    default: null,
  },
  libraryId: {
    type: Number,
    default: null,
  },
});

const emit = defineEmits(["close", "saved"]);

const { t } = useI18n();

const libraries = ref([]);
const loading = ref(false);
const error = ref("");
const filterCriteriaError = ref("");

const form = ref({
  library_id: null,
  name: "",
  filter_criteria: {
    order_by: "scanned_at",
    order: "DESC",
    limit: 20,
  },
  visible_on_homepage: false,
  visible_on_recommend: false,
});

const filterCriteriaJson = computed({
  get() {
    try {
      return JSON.stringify(form.value.filter_criteria, null, 2);
    } catch {
      return "{}";
    }
  },
  set(value) {
    try {
      const parsed = JSON.parse(value);
      form.value.filter_criteria = parsed;
      filterCriteriaError.value = "";
    } catch (e) {
      filterCriteriaError.value = t("recommendationRows.invalidJson");
    }
  },
});

const previewDisplayName = computed(() => {
  if (!form.value.name) return "";

  const selectedLibrary = libraries.value.find((lib) => lib.id === form.value.library_id);
  const libraryName = selectedLibrary?.name || "Library Name";

  // If name contains %LIBRARY_NAME%, replace it; otherwise use name as-is
  // Also support backward compatibility with {library_name}
  let displayName = form.value.name;
  if (displayName.includes("%LIBRARY_NAME%")) {
    displayName = displayName.replace("%LIBRARY_NAME%", libraryName);
  } else if (displayName.includes("{library_name}")) {
    displayName = displayName.replace("{library_name}", libraryName);
  }

  return displayName;
});

// Watch for filter criteria changes to validate
watch(
  () => form.value.filter_criteria,
  () => {
    filterCriteriaError.value = "";
  },
  { deep: true },
);

async function loadLibraries() {
  try {
    libraries.value = await libraryApi.getAllLibraries();
  } catch (err) {
    console.error("Failed to load libraries:", err);
    error.value = err.data?.detail || t("libraries.loadFailed");
  }
}

function initializeForm() {
  if (props.row) {
    form.value = {
      library_id: props.row.library_id,
      name: props.row.name,
      filter_criteria: props.row.filter_criteria,
      visible_on_homepage: props.row.visible_on_homepage,
      visible_on_recommend: props.row.visible_on_recommend,
    };
  } else {
    form.value = {
      library_id: props.libraryId || null,
      name: "",
      filter_criteria: {
        order_by: "scanned_at",
        order: "DESC",
        limit: 20,
      },
      visible_on_homepage: false,
      visible_on_recommend: false,
    };
  }
}

async function handleSubmit() {
  if (filterCriteriaError.value) {
    return;
  }

  loading.value = true;
  error.value = "";

  try {
    const data = {
      library_id: form.value.library_id,
      name: form.value.name,
      filter_criteria: form.value.filter_criteria,
      visible_on_homepage: form.value.visible_on_homepage,
      visible_on_recommend: form.value.visible_on_recommend,
    };

    if (props.row) {
      const updateData = { ...data };
      if (props.row.is_special) {
        delete updateData.library_id;
        delete updateData.filter_criteria;
      } else {
        delete updateData.library_id;
      }
      await rowApi.updateRow(props.row.id, updateData);
    } else {
      // If libraryId prop is provided, use the library-specific endpoint
      if (props.libraryId) {
        await rowApi.addLibraryRow(Number(props.libraryId), data);
      } else {
        await rowApi.createRow(data);
      }
    }

    emit("saved");
  } catch (err) {
    console.error("Failed to save recommendation row:", err);
    error.value = err.data?.detail || t("recommendationRows.saveFailed");
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await loadLibraries();
  initializeForm();
});
</script>

<template>
  <div
    class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 overflow-y-auto py-8"
    @click.self="$emit('close')"
  >
    <div class="bg-gray-800 rounded-lg p-6 w-full max-w-2xl my-auto" @click.stop>
      <h3 class="text-xl font-semibold text-white mb-4">
        {{ row ? $t('recommendationRows.edit') : $t('recommendationRows.add') }}
      </h3>

      <form @submit.prevent="handleSubmit">
        <div class="space-y-4">
          <!-- Library -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('recommendationRows.library') }} <span class="text-red-400">*</span>
            </label>
            <select
              v-model="form.library_id"
              required
              :disabled="!!row || !!libraryId"
              class="w-full px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="">{{ $t('common.select') }}</option>
              <option v-for="lib in libraries" :key="lib.id" :value="lib.id">
                {{ lib.name }}
              </option>
            </select>
          </div>

          <!-- Name -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('recommendationRows.name') }} <span class="text-red-400">*</span>
            </label>
            <input
              v-model="form.name"
              type="text"
              required
              class="w-full px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500"
              :placeholder="$t('recommendationRows.namePlaceholder')"
            />
          </div>

          <!-- Display Name Preview -->
          <div v-if="form.name" class="bg-gray-700/50 rounded-md p-3 border border-gray-600">
            <p class="text-xs text-gray-400 mb-1">{{ $t('recommendationRows.previewLabel') }}</p>
            <p class="text-sm text-white font-medium">
              {{ previewDisplayName }}
            </p>
          </div>

          <!-- Filter Criteria -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('recommendationRows.filterCriteria') }} <span class="text-red-400">*</span>
            </label>
            <textarea
              v-model="filterCriteriaJson"
              :disabled="row?.is_special"
              rows="6"
              class="w-full px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500 font-mono text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              :placeholder="$t('recommendationRows.filterCriteriaPlaceholder')"
            ></textarea>
            <p v-if="row?.is_special" class="mt-1 text-xs text-yellow-400">
              {{ $t('recommendationRows.filterCriteriaCannotChange') }}
            </p>
            <p v-else class="mt-1 text-xs text-gray-400">
              {{ $t('recommendationRows.filterCriteriaHelp') }}
            </p>
            <div v-if="filterCriteriaError" class="mt-2 text-red-400 text-sm">
              {{ filterCriteriaError }}
            </div>
          </div>

          <!-- Visibility Flags -->
          <div class="flex items-center space-x-6">
            <div class="flex items-center">
              <input
                v-model="form.visible_on_homepage"
                type="checkbox"
                id="visible_on_homepage"
                class="w-4 h-4 text-primary-600 bg-gray-700 border-gray-600 rounded-sm focus:ring-primary-500"
              />
              <label for="visible_on_homepage" class="ml-2 text-sm font-medium text-gray-300">
                {{ $t('recommendationRows.visibleOnHomepage') }}
              </label>
            </div>
            <div class="flex items-center">
              <input
                v-model="form.visible_on_recommend"
                type="checkbox"
                id="visible_on_recommend"
                class="w-4 h-4 text-primary-600 bg-gray-700 border-gray-600 rounded-sm focus:ring-primary-500"
              />
              <label for="visible_on_recommend" class="ml-2 text-sm font-medium text-gray-300">
                {{ $t('recommendationRows.visibleOnRecommend') }}
              </label>
            </div>
          </div>

          <!-- Special Row Info -->
          <div
            v-if="row?.is_special"
            class="bg-yellow-900/20 border border-yellow-700 rounded-md p-3"
          >
            <p class="text-sm text-yellow-300">
              {{ $t('recommendationRows.specialRowInfo') }}
            </p>
          </div>
        </div>

        <!-- Error message -->
        <div v-if="error" class="mt-4 text-red-400 text-sm">
          {{ error }}
        </div>

        <!-- Actions -->
        <div class="mt-6 flex justify-end space-x-3">
          <button
            type="button"
            @click="$emit('close')"
            class="px-4 py-2 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors"
          >
            {{ $t('common.cancel') }}
          </button>
          <button
            type="submit"
            :disabled="loading || !!filterCriteriaError"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors disabled:opacity-50"
          >
            {{ loading ? $t('common.loading') : $t('common.save') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
