<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { libraries as libraryApi } from "@/api/client";

const route = useRoute();
const libraries = ref([]);

function isActive(libraryId) {
  const routeId = Array.isArray(route.params.id) ? route.params.id[0] : route.params.id;
  return route.name === "library" && parseInt(routeId, 10) === libraryId;
}

async function loadLibraries() {
  try {
    libraries.value = await libraryApi.getLibraries();
  } catch (err) {
    console.error("Failed to load libraries:", err);
    libraries.value = [];
  }
}

onMounted(async () => {
  await loadLibraries();
});
</script>

<template>
  <nav class="bg-gray-800/95 backdrop-blur-xs border-b border-gray-700">
    <div class="container mx-auto px-6 py-3">
      <div class="flex items-center space-x-4">
        <span class="text-sm font-medium text-gray-400">{{ $t('common.libraries') }}:</span>
        <div class="flex items-center space-x-2">
          <router-link
            v-for="library in libraries"
            :key="library.id"
            :to="`/library/${library.id}`"
            class="group px-3 text-sm font-medium transition-colors"
            :class="
              isActive(library.id)
                ? 'text-white'
                : 'text-gray-300 hover:text-white'
            "
          >
            <span
              class="inline-block max-w-full truncate border-b-2 py-1 transition-colors"
              :class="isActive(library.id) ? 'border-primary-500' : 'border-transparent group-hover:border-gray-600'"
            >
              {{ library.name }}
            </span>
          </router-link>
        </div>
      </div>
    </div>
  </nav>
</template>
