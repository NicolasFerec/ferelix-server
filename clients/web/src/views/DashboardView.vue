<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import MetadataJobsPanel from "@/components/MetadataJobsPanel.vue";
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
  <div class="min-h-screen bg-background">
    <MenuBar />
    <div class="mx-auto flex max-w-[1800px] flex-col lg:flex-row">
      <aside class="border-b border-outline lg:w-60 lg:shrink-0 lg:border-b-0 lg:border-r">
        <nav class="flex gap-2 overflow-x-auto p-4 lg:sticky lg:top-24 lg:flex-col" :aria-label="$t('dashboard.title')">
          <RouterLink v-for="section in sectionIds" :key="section" :to="sectionPath(section)"
            class="shrink-0 rounded-xl px-4 py-3 text-sm font-medium transition-colors"
            :class="activeSection === section ? 'bg-primary-500/15 text-primary-200' : 'text-muted hover:bg-white/5 hover:text-white'"
            :aria-current="activeSection === section ? 'page' : undefined">
            {{ $t(section === 'dashboard' ? 'dashboard.title' : `dashboard.${section}`) }}
          </RouterLink>
        </nav>
      </aside>
      <main id="main-content" class="min-w-0 flex-1 px-5 py-8 sm:p-8 lg:p-10">
        <StreamsPanel v-if="activeSection === 'dashboard'" />
        <LibraryList v-else-if="activeSection === 'libraries'" />
        <div v-else-if="activeSection === 'jobs'"><JobsPanel /><MetadataJobsPanel /></div>
        <ServerLogsPanel v-else-if="activeSection === 'logs'" />
        <UserManagementPanel v-else-if="activeSection === 'users'" />
        <SettingsPanel v-else-if="activeSection === 'settings'" />
      </main>
    </div>
  </div>
</template>
