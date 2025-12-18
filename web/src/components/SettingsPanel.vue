<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { SettingsUpdate, settings as settingsApi } from "@/api/client";

const { t } = useI18n();

const loading = ref(false);
const saving = ref(false);
const loadError = ref("");
const saveError = ref("");
const showSuccess = ref(false);
const showError = ref(false);

const originalSettings = ref(null);
const formData = ref({
  library_scan_interval_minutes: 120,
  cleanup_schedule_hour: 3,
  cleanup_schedule_minute: 0,
  cleanup_grace_period_days: 30,
});

const hasChanges = computed(() => {
  if (!originalSettings.value) return false;

  return (
    formData.value.library_scan_interval_minutes !==
      originalSettings.value.library_scan_interval_minutes ||
    formData.value.cleanup_schedule_hour !== originalSettings.value.cleanup_schedule_hour ||
    formData.value.cleanup_schedule_minute !== originalSettings.value.cleanup_schedule_minute ||
    formData.value.cleanup_grace_period_days !== originalSettings.value.cleanup_grace_period_days
  );
});

async function loadSettings() {
  loading.value = true;
  loadError.value = "";
  showSuccess.value = false;
  showError.value = false;

  try {
    const settings = await settingsApi.getSettings();
    originalSettings.value = { ...settings };
    formData.value = {
      library_scan_interval_minutes: settings.library_scan_interval_minutes,
      cleanup_schedule_hour: settings.cleanup_schedule_hour,
      cleanup_schedule_minute: settings.cleanup_schedule_minute,
      cleanup_grace_period_days: settings.cleanup_grace_period_days,
    };
  } catch (err) {
    console.error("Failed to load settings:", err);
    loadError.value = err.data?.detail || t("settings.loadError");
  } finally {
    loading.value = false;
  }
}

async function saveSettings() {
  saving.value = true;
  saveError.value = "";
  showSuccess.value = false;
  showError.value = false;

  try {
    const updateData: SettingsUpdate = {};

    if (
      formData.value.library_scan_interval_minutes !==
      originalSettings.value.library_scan_interval_minutes
    ) {
      updateData.library_scan_interval_minutes = formData.value.library_scan_interval_minutes;
    }
    if (formData.value.cleanup_schedule_hour !== originalSettings.value.cleanup_schedule_hour) {
      updateData.cleanup_schedule_hour = formData.value.cleanup_schedule_hour;
    }
    if (formData.value.cleanup_schedule_minute !== originalSettings.value.cleanup_schedule_minute) {
      updateData.cleanup_schedule_minute = formData.value.cleanup_schedule_minute;
    }
    if (
      formData.value.cleanup_grace_period_days !== originalSettings.value.cleanup_grace_period_days
    ) {
      updateData.cleanup_grace_period_days = formData.value.cleanup_grace_period_days;
    }

    const updatedSettings = await settingsApi.updateSettings(updateData);
    originalSettings.value = { ...updatedSettings };

    showSuccess.value = true;
    setTimeout(() => {
      showSuccess.value = false;
    }, 3000);
  } catch (err) {
    console.error("Failed to save settings:", err);
    saveError.value = err.data?.detail || t("settings.saveError");
    showError.value = true;
    setTimeout(() => {
      showError.value = false;
    }, 5000);
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  loadSettings();
});
</script>

<template>
  <div class="settings-panel">
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-semibold text-white">{{ $t('settings.title') }}</h2>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center text-gray-400 py-12">
      {{ $t('common.loading') }}
    </div>

    <!-- Error state -->
    <div v-else-if="loadError" class="text-center text-red-400 py-12">
      <p>{{ loadError }}</p>
      <button
        @click="loadSettings"
        class="mt-4 px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ $t('common.retry') }}
      </button>
    </div>

    <!-- Settings form -->
    <div v-else class="space-y-8">
      <!-- Library Scanner Settings -->
      <div class="bg-gray-800 rounded-lg p-6">
        <h3 class="text-xl font-semibold text-white mb-2">
          {{ $t('settings.libraryScanner.title') }}
        </h3>
        <p class="text-gray-400 text-sm mb-4">
          {{ $t('settings.libraryScanner.description') }}
        </p>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.libraryScanner.interval') }}
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="formData.library_scan_interval_minutes"
                type="number"
                min="1"
                class="flex-1 px-4 py-2 bg-gray-700 text-white rounded-md border border-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                :disabled="saving"
              />
              <span class="text-gray-400 whitespace-nowrap">
                {{ $t('settings.libraryScanner.minutes') }}
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-500">
              {{ $t('settings.libraryScanner.intervalHint') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Database Cleanup Settings -->
      <div class="bg-gray-800 rounded-lg p-6">
        <h3 class="text-xl font-semibold text-white mb-2">
          {{ $t('settings.cleanupJob.title') }}
        </h3>
        <p class="text-gray-400 text-sm mb-4">
          {{ $t('settings.cleanupJob.description') }}
        </p>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.cleanupJob.schedule') }}
              <span class="text-gray-500 text-xs ml-1">
                {{ $t('settings.cleanupJob.timeFormat') }}
              </span>
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="formData.cleanup_schedule_hour"
                type="number"
                min="0"
                max="23"
                class="w-24 px-4 py-2 bg-gray-700 text-white rounded-md border border-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="3"
                :disabled="saving"
              />
              <span class="text-gray-400">:</span>
              <input
                v-model.number="formData.cleanup_schedule_minute"
                type="number"
                min="0"
                max="59"
                class="w-24 px-4 py-2 bg-gray-700 text-white rounded-md border border-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                placeholder="0"
                :disabled="saving"
              />
            </div>
            <p class="mt-1 text-xs text-gray-500">
              {{ $t('settings.cleanupJob.scheduleHint') }}
            </p>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.cleanupJob.gracePeriod') }}
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model.number="formData.cleanup_grace_period_days"
                type="number"
                min="1"
                class="flex-1 px-4 py-2 bg-gray-700 text-white rounded-md border border-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                :disabled="saving"
              />
              <span class="text-gray-400 whitespace-nowrap">
                {{ $t('settings.cleanupJob.days') }}
              </span>
            </div>
            <p class="mt-1 text-xs text-gray-500">
              {{ $t('settings.cleanupJob.gracePeriodHint') }}
            </p>
          </div>
        </div>
      </div>

      <!-- Save button -->
      <div class="flex justify-end gap-4">
        <button
          @click="loadSettings"
          :disabled="saving"
          class="px-6 py-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:cursor-not-allowed text-white rounded-md transition-colors"
        >
          {{ $t('common.cancel') }}
        </button>
        <button
          @click="saveSettings"
          :disabled="saving || !hasChanges"
          class="px-6 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-md transition-colors"
        >
          {{ saving ? $t('settings.saving') : $t('common.save') }}
        </button>
      </div>
    </div>

    <!-- Success notification -->
    <div
      v-if="showSuccess"
      class="fixed top-4 right-4 bg-green-600 text-white px-6 py-3 rounded-md shadow-lg z-50"
    >
      {{ $t('settings.saveSuccess') }}
    </div>

    <!-- Error notification -->
    <div
      v-if="showError"
      class="fixed top-4 right-4 bg-red-600 text-white px-6 py-3 rounded-md shadow-lg z-50"
    >
      {{ saveError || $t('settings.saveError') }}
    </div>
  </div>
</template>
