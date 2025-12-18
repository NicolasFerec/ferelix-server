<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi } from "@/api/client";
import DirectoryBrowser from "./DirectoryBrowser.vue";

const props = defineProps({
  library: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(["close", "saved"]);

const { t } = useI18n();

const form = ref({
  name: "",
  path: "",
  library_type: "movie",
  enabled: true,
});

const loading = ref(false);
const error = ref("");
const showBrowser = ref(false);

// Initialize form with library data if editing
watch(
  () => props.library,
  (library) => {
    if (library) {
      form.value = {
        name: library.name || "",
        path: library.path,
        library_type: library.library_type || "movie",
        enabled: library.enabled,
      };
    } else {
      form.value = {
        name: "",
        path: "",
        library_type: "movie",
        enabled: true,
      };
    }
    error.value = "";
  },
  { immediate: true },
);

async function handleSubmit() {
  if (!form.value.name.trim()) {
    error.value = t("libraries.nameRequired");
    return;
  }
  if (!form.value.path.trim()) {
    error.value = t("libraries.pathRequired");
    return;
  }

  loading.value = true;
  error.value = "";

  try {
    if (props.library) {
      // Update existing library
      await libraryApi.updateLibrary(props.library.id, {
        name: form.value.name,
        path: form.value.path,
        library_type: form.value.library_type,
        enabled: form.value.enabled,
      });
    } else {
      // Create new library
      await libraryApi.createLibrary(
        form.value.name,
        form.value.path,
        form.value.library_type as "movie" | "show",
        form.value.enabled,
      );
    }
    emit("saved");
  } catch (err) {
    console.error("Failed to save library:", err);
    error.value =
      err.data?.detail ||
      (props.library ? t("libraries.updateFailed") : t("libraries.createFailed"));
  } finally {
    loading.value = false;
  }
}

function handlePathSelect(path) {
  form.value.path = path;
  showBrowser.value = false;
}
</script>

<template>
  <div
    class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
    @click.self="$emit('close')"
  >
    <div class="bg-gray-800 rounded-lg p-6 w-full max-w-md" @click.stop>
      <h3 class="text-xl font-semibold text-white mb-4">
        {{ library ? $t('libraries.edit') : $t('libraries.add') }}
      </h3>

      <form @submit.prevent="handleSubmit">
        <div class="space-y-4">
          <!-- Name -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('libraries.name') }}
            </label>
            <input
              v-model="form.name"
              type="text"
              required
              class="w-full px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500"
              placeholder="My Library"
            />
          </div>

          <!-- Path -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('libraries.path') }}
            </label>
            <div class="flex space-x-2">
              <input
                v-model="form.path"
                type="text"
                required
                class="flex-1 px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500"
                placeholder="/path/to/library"
              />
              <button
                type="button"
                @click="showBrowser = true"
                class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-md transition-colors text-sm font-medium"
                :title="$t('libraries.browse')"
              >
                {{ $t('libraries.browse') }}
              </button>
            </div>
          </div>

          <!-- Library Type -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('libraries.typeLabel') }}
            </label>
            <select
              v-model="form.library_type"
              class="w-full px-3 py-2 bg-gray-700 text-white rounded-md focus:outline-hidden focus:ring-2 focus:ring-primary-500"
            >
              <option value="movie">{{ $t('libraries.type.movie') }}</option>
              <option value="tv_show">{{ $t('libraries.type.tv_show') }}</option>
            </select>
          </div>

          <!-- Enabled -->
          <div class="flex items-center">
            <input
              v-model="form.enabled"
              type="checkbox"
              id="enabled"
              class="w-4 h-4 text-primary-600 bg-gray-700 border-gray-600 rounded-sm focus:ring-primary-500"
            />
            <label for="enabled" class="ml-2 text-sm font-medium text-gray-300">
              {{ $t('libraries.enabled') }}
            </label>
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
            :disabled="loading"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors disabled:opacity-50"
          >
            {{ loading ? $t('common.loading') : $t('common.save') }}
          </button>
        </div>
      </form>
    </div>

    <!-- Directory Browser -->
    <DirectoryBrowser
      v-if="showBrowser"
      :initial-path="form.path"
      @close="showBrowser = false"
      @select="handlePathSelect"
    />
  </div>
</template>
