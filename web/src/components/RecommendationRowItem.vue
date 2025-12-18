<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { libraries as libraryApi } from "@/api/client";

const props = defineProps({
  row: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(["edit", "delete"]);

const { t } = useI18n();

const showDropdown = ref(false);
const dropdownRef = ref(null);
const library_name = ref("");

async function loadLibraryName() {
  try {
    const libraries = await libraryApi.getAllLibraries();
    const library = libraries.find((lib) => lib.id === props.row.library_id);
    library_name.value = library?.name || "Unknown";
  } catch (err) {
    console.error("Failed to load library name:", err);
    library_name.value = "Unknown";
  }
}

function handleClickOutside(event) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target)) {
    showDropdown.value = false;
  }
}

function handleEdit() {
  showDropdown.value = false;
  emit("edit", props.row);
}

function handleDelete() {
  showDropdown.value = false;
  emit("delete", props.row);
}

onMounted(() => {
  document.addEventListener("click", handleClickOutside);
  loadLibraryName();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleClickOutside);
});
</script>

<template>
  <tr class="hover:bg-gray-700">
    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
      {{ row.name }}
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
      {{ library_name }}
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm">
      <span
        :class="[
          'px-2 py-1 rounded-full text-xs font-medium',
          row.visible_on_homepage ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400',
        ]"
      >
        {{ row.visible_on_homepage ? $t('common.enabled') : $t('common.disabled') }}
      </span>
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm">
      <span
        :class="[
          'px-2 py-1 rounded-full text-xs font-medium',
          row.visible_on_recommend ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400',
        ]"
      >
        {{ row.visible_on_recommend ? $t('common.enabled') : $t('common.disabled') }}
      </span>
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-sm">
      <span
        v-if="row.is_special"
        class="px-2 py-1 rounded-full text-xs font-medium bg-yellow-900 text-yellow-300"
      >
        {{ $t('recommendationRows.special') }}
      </span>
      <span v-else class="text-gray-500">-</span>
    </td>
    <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium relative">
      <div ref="dropdownRef" class="relative inline-block text-left">
        <button
          @click="showDropdown = !showDropdown"
          class="inline-flex justify-center w-full rounded-md border border-gray-600 shadow-xs px-4 py-2 bg-gray-700 text-sm font-medium text-gray-300 hover:bg-gray-600 focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-primary-500"
        >
          {{ $t('common.actions') }}
          <svg
            class="-mr-1 ml-2 h-5 w-5"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
              clip-rule="evenodd"
            />
          </svg>
        </button>

        <div
          v-if="showDropdown"
          class="origin-top-right absolute right-0 mt-2 w-56 rounded-md shadow-2xl bg-gray-600 border border-gray-500 focus:outline-hidden z-50"
        >
          <div class="py-1">
            <button
              @click="handleEdit"
              class="block w-full text-left px-4 py-2 text-sm text-gray-200 hover:bg-gray-500"
            >
              {{ $t('common.edit') }}
            </button>
            <button
              v-if="!row.is_special"
              @click="handleDelete"
              class="block w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-gray-500"
            >
              {{ $t('common.delete') }}
            </button>
            <button
              v-else
              disabled
              class="block w-full text-left px-4 py-2 text-sm text-gray-500 cursor-not-allowed"
            >
              {{ $t('recommendationRows.cannotDelete') }}
            </button>
          </div>
        </div>
      </div>
    </td>
  </tr>
</template>
