<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import JobsPanel from "../components/JobsPanel.vue";
import LibraryList from "../components/LibraryList.vue";
import MenuBar from "../components/MenuBar.vue";
import ServerLogsPanel from "../components/ServerLogsPanel.vue";
import SettingsPanel from "../components/SettingsPanel.vue";
import StreamsPanel from "../components/StreamsPanel.vue";
import UserManagementPanel from "../components/UserManagementPanel.vue";

const route = useRoute();
const router = useRouter();
const sectionIds = ["dashboard", "libraries", "jobs", "logs", "users", "settings"] as const;
type DashboardSection = (typeof sectionIds)[number];

const activeSection = computed<DashboardSection>(() => {
  const section = route.params.section;
  const sectionId = Array.isArray(section) ? section[0] : section;
  if (!sectionId) return "dashboard";
  return sectionIds.includes(sectionId as DashboardSection) ? (sectionId as DashboardSection) : "dashboard";
});

const sectionPath = (section: DashboardSection) => (section === "dashboard" ? "/dashboard" : `/dashboard/${section}`);

watch(
  () => route.params.section,
  (section) => {
    const sectionId = Array.isArray(section) ? section[0] : section;
    if (sectionId && !sectionIds.includes(sectionId as DashboardSection)) {
      router.replace("/dashboard");
    }
  },
  { immediate: true },
);
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
              <router-link
                :to="sectionPath('dashboard')"
                :class="[
                  'group block w-full py-2 text-left font-semibold transition-colors',
                  activeSection === 'dashboard'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'dashboard'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.title') }}
                </span>
              </router-link>
            </li>
            <li>
              <router-link
                :to="sectionPath('libraries')"
                :class="[
                  'group block w-full py-2 text-left transition-colors',
                  activeSection === 'libraries'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'libraries'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.libraries') }}
                </span>
              </router-link>
            </li>
            <li>
              <router-link
                :to="sectionPath('jobs')"
                :class="[
                  'group block w-full py-2 text-left transition-colors',
                  activeSection === 'jobs'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'jobs'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.jobs') }}
                </span>
              </router-link>
            </li>
            <li>
              <router-link
                :to="sectionPath('logs')"
                :class="[
                  'group block w-full py-2 text-left transition-colors',
                  activeSection === 'logs'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'logs'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.logs') }}
                </span>
              </router-link>
            </li>
            <li>
              <router-link
                :to="sectionPath('users')"
                :class="[
                  'group block w-full py-2 text-left transition-colors',
                  activeSection === 'users'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'users'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.users') }}
                </span>
              </router-link>
            </li>
            <li>
              <router-link
                :to="sectionPath('settings')"
                :class="[
                  'group block w-full py-2 text-left transition-colors',
                  activeSection === 'settings'
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white',
                ]"
              >
                <span
                  :class="[
                    'inline-block border-l-2 px-4 transition-colors',
                    activeSection === 'settings'
                      ? 'border-primary-500'
                      : 'border-transparent group-hover:border-gray-600',
                  ]"
                >
                  {{ $t('dashboard.settings') }}
                </span>
              </router-link>
            </li>
          </ul>
        </nav>
      </aside>

      <!-- Main content -->
      <main class="flex-1 overflow-y-auto p-8">
        <StreamsPanel v-if="activeSection === 'dashboard'" />
        <LibraryList v-else-if="activeSection === 'libraries'" />
        <JobsPanel v-else-if="activeSection === 'jobs'" />
        <ServerLogsPanel v-else-if="activeSection === 'logs'" />
        <UserManagementPanel v-else-if="activeSection === 'users'" />
        <SettingsPanel v-else-if="activeSection === 'settings'" />
        <div v-else class="text-center text-gray-400 py-12">
          {{ $t('dashboard.comingSoon') }}
        </div>
      </main>
    </div>
  </div>
</template>
