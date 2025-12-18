<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi } from "@/api/client";

const props = defineProps({
  initialPath: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["close", "select"]);

const { t } = useI18n();

const currentPath = ref("");
const items = ref([]);
const loading = ref(false);
const error = ref("");
const history = ref([]);
const historyIndex = ref(-1);

const canGoBack = computed(() => historyIndex.value > 0);
const canGoForward = computed(() => historyIndex.value < history.value.length - 1);

// Detect OS and set initial path
function getInitialPath() {
  if (props.initialPath) {
    return props.initialPath;
  }

  // Try to detect OS and set appropriate root
  // Default to Unix root, but could be enhanced with OS detection
  return "/";
}

async function loadDirectory(path, addToHistory = true) {
  loading.value = true;
  error.value = "";

  try {
    const directoryItems = await libraryApi.browseDirectory(path);
    items.value = directoryItems;
    currentPath.value = path;

    // Add to history if not navigating through history
    if (addToHistory) {
      // Remove any future history if we're not at the end
      if (historyIndex.value < history.value.length - 1) {
        history.value = history.value.slice(0, historyIndex.value + 1);
      }
      // Add new path to history
      history.value.push(path);
      historyIndex.value = history.value.length - 1;
    }
  } catch (err) {
    console.error("Failed to browse directory:", err);
    error.value = err.data?.detail || t("libraries.browseError");
    items.value = [];
  } finally {
    loading.value = false;
  }
}

function handleItemClick(item) {
  if (item.is_directory) {
    loadDirectory(item.path, true);
  }
}

function navigateToPath() {
  if (currentPath.value.trim()) {
    loadDirectory(currentPath.value.trim(), true);
  }
}

function goBack() {
  if (canGoBack.value) {
    historyIndex.value--;
    loadDirectory(history.value[historyIndex.value], false);
  }
}

function goForward() {
  if (canGoForward.value) {
    historyIndex.value++;
    loadDirectory(history.value[historyIndex.value], false);
  }
}

function goUp() {
  if (currentPath.value === "/") {
    return;
  }

  const parts = currentPath.value.split("/").filter((part) => part.length > 0);

  if (parts.length === 0) {
    loadDirectory("/", true);
  } else {
    parts.pop();
    const parentPath = parts.length === 0 ? "/" : `/${parts.join("/")}`;
    loadDirectory(parentPath, true);
  }
}

function selectCurrentPath() {
  emit("select", currentPath.value);
  emit("close");
}

onMounted(() => {
  const initialPath = getInitialPath();
  history.value = [initialPath];
  historyIndex.value = 0;
  loadDirectory(initialPath, false);
});
</script>

<template>
  <div
    class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
    @click.self="$emit('close')"
  >
    <div class="bg-gray-800 rounded-lg p-6 w-full max-w-2xl max-h-[80vh] flex flex-col" @click.stop>
      <h3 class="text-xl font-semibold text-white mb-4">
        {{ $t('libraries.browseDirectory') }}
      </h3>

      <!-- Navigation Controls -->
      <div class="mb-4 flex items-center space-x-2">
        <button
          @click="goBack"
          :disabled="!canGoBack"
          class="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :title="$t('libraries.goBack')"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 19l-7-7 7-7"
            />
          </svg>
        </button>
        <button
          @click="goForward"
          :disabled="!canGoForward"
          class="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :title="$t('libraries.goForward')"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9 5l7 7-7 7"
            />
          </svg>
        </button>
        <button
          @click="goUp"
          :disabled="currentPath === '/'"
          class="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          :title="$t('libraries.goUp')"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M5 10l7-7m0 0l7 7m-7-7v18"
            />
          </svg>
        </button>
        <input
          v-model="currentPath"
          type="text"
          @keyup.enter="navigateToPath"
          class="flex-1 px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500 text-sm"
          :placeholder="$t('libraries.enterPath')"
        />
      </div>

      <!-- Directory Contents -->
      <div class="flex-1 overflow-y-auto border border-gray-700 rounded-md bg-gray-900">
        <div v-if="loading" class="p-8 text-center text-gray-400">
          {{ $t('common.loading') }}...
        </div>
        <div v-else-if="error" class="p-4 text-red-400 text-sm">
          {{ error }}
        </div>
        <div v-else-if="items.length === 0" class="p-8 text-center text-gray-400">
          {{ $t('libraries.emptyDirectory') }}
        </div>
        <div v-else class="divide-y divide-gray-700">
          <button
            v-for="item in items"
            :key="item.path"
            @click="handleItemClick(item)"
            class="w-full px-4 py-3 text-left hover:bg-gray-700 transition-colors flex items-center space-x-3"
          >
            <svg
              v-if="item.is_directory"
              class="w-5 h-5 text-yellow-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              />
            </svg>
            <svg
              v-else
              class="w-5 h-5 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <span class="text-white flex-1">{{ item.name }}</span>
          </button>
        </div>
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
          type="button"
          @click="selectCurrentPath"
          :disabled="loading"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors disabled:opacity-50"
        >
          {{ $t('common.select') }}
        </button>
      </div>
    </div>
  </div>
</template>
