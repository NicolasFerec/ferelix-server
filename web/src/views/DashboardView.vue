<script setup lang="ts">
import { ref } from "vue";
import JobsPanel from "../components/JobsPanel.vue";
import LibraryList from "../components/LibraryList.vue";
import MenuBar from "../components/MenuBar.vue";
import SettingsPanel from "../components/SettingsPanel.vue";
import StreamsPanel from "../components/StreamsPanel.vue";
import UserManagementPanel from "../components/UserManagementPanel.vue";

const activeSection = ref("dashboard");
</script>

<template>
  <div class="dashboard-view min-h-screen bg-gray-900">
    <MenuBar />

    <div class="flex h-[calc(100vh-73px)]">
      <!-- Sidebar -->
      <aside class="w-64 bg-gray-800 border-r border-gray-700">
        <nav class="p-4">
          <ul class="space-y-1">
            <li>
              <button
                @click="activeSection = 'dashboard'"
                :class="[
                  'w-full border-l-2 px-4 py-2 text-left font-semibold transition-colors',
                  activeSection === 'dashboard'
                    ? 'border-primary-500 text-white'
                    : 'border-transparent text-gray-300 hover:border-gray-600 hover:text-white',
                ]"
              >
                {{ $t('dashboard.title') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'libraries'"
                :class="[
                  'w-full border-l-2 px-4 py-2 text-left transition-colors',
                  activeSection === 'libraries'
                    ? 'border-primary-500 text-white'
                    : 'border-transparent text-gray-300 hover:border-gray-600 hover:text-white',
                ]"
              >
                {{ $t('dashboard.libraries') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'jobs'"
                :class="[
                  'w-full border-l-2 px-4 py-2 text-left transition-colors',
                  activeSection === 'jobs'
                    ? 'border-primary-500 text-white'
                    : 'border-transparent text-gray-300 hover:border-gray-600 hover:text-white',
                ]"
              >
                {{ $t('dashboard.jobs') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'users'"
                :class="[
                  'w-full border-l-2 px-4 py-2 text-left transition-colors',
                  activeSection === 'users'
                    ? 'border-primary-500 text-white'
                    : 'border-transparent text-gray-300 hover:border-gray-600 hover:text-white',
                ]"
              >
                {{ $t('dashboard.users') }}
              </button>
            </li>
            <li>
              <button
                @click="activeSection = 'settings'"
                :class="[
                  'w-full border-l-2 px-4 py-2 text-left transition-colors',
                  activeSection === 'settings'
                    ? 'border-primary-500 text-white'
                    : 'border-transparent text-gray-300 hover:border-gray-600 hover:text-white',
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
        <StreamsPanel v-if="activeSection === 'dashboard'" />
        <LibraryList v-else-if="activeSection === 'libraries'" />
        <JobsPanel v-else-if="activeSection === 'jobs'" />
        <UserManagementPanel v-else-if="activeSection === 'users'" />
        <SettingsPanel v-else-if="activeSection === 'settings'" />
        <div v-else class="text-center text-gray-400 py-12">
          {{ $t('dashboard.comingSoon') }}
        </div>
      </main>
    </div>
  </div>
</template>
