<script setup lang="ts">
import { ref } from "vue";
import JobsPanel from "../components/JobsPanel.vue";
import LibraryList from "../components/LibraryList.vue";
import MenuBar from "../components/MenuBar.vue";
import SettingsPanel from "../components/SettingsPanel.vue";

const activeSection = ref("libraries");
</script>

<template>
  <div class="dashboard-view min-h-screen bg-gray-900">
    <MenuBar />

    <div class="flex h-[calc(100vh-73px)]">
      <!-- Sidebar -->
      <aside class="w-64 bg-gray-800 border-r border-gray-700">
        <nav class="p-4">
          <h2 class="text-xl font-semibold text-white mb-4">{{ $t('dashboard.title') }}</h2>
          <ul class="space-y-2">
            <li>
              <button
                @click="activeSection = 'libraries'"
                :class="[
                  'w-full text-left px-4 py-2 rounded-md transition-colors',
                  activeSection === 'libraries'
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white',
                ]"
              >
                {{ $t('dashboard.libraries') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'jobs'"
                :class="[
                  'w-full text-left px-4 py-2 rounded-md transition-colors',
                  activeSection === 'jobs'
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white',
                ]"
              >
                {{ $t('dashboard.jobs') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'users'"
                :class="[
                  'w-full text-left px-4 py-2 rounded-md transition-colors',
                  activeSection === 'users'
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white',
                ]"
                disabled
              >
                {{ $t('dashboard.users') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'settings'"
                :class="[
                  'w-full text-left px-4 py-2 rounded-md transition-colors',
                  activeSection === 'settings'
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-300 hover:bg-gray-700 hover:text-white',
                ]"
              >
                {{ $t('dashboard.settings') }}
              </button>
            </li>
          </ul>
        </nav>
      </aside>

      <!-- Main content -->
      <main class="flex-1 overflow-y-auto p-8">
        <LibraryList v-if="activeSection === 'libraries'" />
        <JobsPanel v-else-if="activeSection === 'jobs'" />
        <SettingsPanel v-else-if="activeSection === 'settings'" />
        <div v-else class="text-center text-gray-400 py-12">
          {{ $t('dashboard.comingSoon') }}
        </div>
      </main>
    </div>
  </div>
</template>
