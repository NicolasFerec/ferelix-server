<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  type HardwareAccelerationStatus,
  type Settings,
  type SettingsUpdate,
  settings as settingsApi,
} from "@/api/client";
import { useToast } from "@/composables/useToast";

const { t } = useI18n();
const toast = useToast();

const loading = ref(false);
const saving = ref(false);
const hardwareLoading = ref(false);
const loadError = ref("");
const saveError = ref("");
const hardwareError = ref("");

const originalSettings = ref<Settings | null>(null);
const hardwareStatus = ref<HardwareAccelerationStatus | null>(null);
const formData = ref({
  library_scan_interval_minutes: 120,
  cleanup_schedule_hour: 3,
  cleanup_schedule_minute: 0,
  cleanup_grace_period_days: 30,
  hardware_transcoding_device: "auto",
});

const hasChanges = computed(() => {
  if (!originalSettings.value) return false;

  return (
    formData.value.library_scan_interval_minutes !==
      originalSettings.value.library_scan_interval_minutes ||
    formData.value.cleanup_schedule_hour !== originalSettings.value.cleanup_schedule_hour ||
    formData.value.cleanup_schedule_minute !== originalSettings.value.cleanup_schedule_minute ||
    formData.value.cleanup_grace_period_days !== originalSettings.value.cleanup_grace_period_days ||
    formData.value.hardware_transcoding_device !== originalSettings.value.hardware_transcoding_device
  );
});

const hardwareDeviceOptions = computed(() => [
  {
    id: "software",
    label: t("settings.hardwareTranscoding.software"),
  },
  ...(hardwareStatus.value?.devices || [])
    .filter((device) => device.available)
    .map((device) => ({
      id: device.id,
      label: device.name,
    })),
]);

const selectedHardwareDevice = computed({
  get() {
    if (formData.value.hardware_transcoding_device === "auto") {
      return hardwareStatus.value?.active_device_id || "software";
    }
    return formData.value.hardware_transcoding_device;
  },
  set(deviceId: string) {
    formData.value.hardware_transcoding_device = deviceId;
  },
});

function capabilityLabel(capability) {
  const modes = [];
  if (capability.can_decode) modes.push(t("settings.hardwareTranscoding.decode"));
  if (capability.can_encode) modes.push(t("settings.hardwareTranscoding.encode"));
  return `${capability.codec.toUpperCase()} ${modes.join(" / ")}`;
}

async function loadSettings() {
  loading.value = true;
  loadError.value = "";

  try {
    const settings = await settingsApi.getSettings();
    originalSettings.value = { ...settings };
    formData.value = {
      library_scan_interval_minutes: settings.library_scan_interval_minutes,
      cleanup_schedule_hour: settings.cleanup_schedule_hour,
      cleanup_schedule_minute: settings.cleanup_schedule_minute,
      cleanup_grace_period_days: settings.cleanup_grace_period_days,
      hardware_transcoding_device: settings.hardware_transcoding_device,
    };
  } catch (err) {
    console.error("Failed to load settings:", err);
    loadError.value = err.data?.detail || t("settings.loadError");
  } finally {
    loading.value = false;
  }
}

async function loadHardwareStatus(refresh = false) {
  hardwareLoading.value = true;
  hardwareError.value = "";

  try {
    hardwareStatus.value = await settingsApi.getHardwareTranscodingStatus(refresh);
  } catch (err) {
    console.error("Failed to load hardware transcoding status:", err);
    hardwareError.value = err.data?.detail || t("settings.hardwareTranscoding.loadError");
  } finally {
    hardwareLoading.value = false;
  }
}

async function saveSettings() {
  saving.value = true;
  saveError.value = "";

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
    if (
      formData.value.hardware_transcoding_device !==
      originalSettings.value.hardware_transcoding_device
    ) {
      updateData.hardware_transcoding_device = formData.value.hardware_transcoding_device;
    }

    const updatedSettings = await settingsApi.updateSettings(updateData);
    originalSettings.value = { ...updatedSettings };
    formData.value.hardware_transcoding_device = updatedSettings.hardware_transcoding_device;
    await loadHardwareStatus();

    toast.success(t("settings.saveSuccess"));
  } catch (err) {
    console.error("Failed to save settings:", err);
    saveError.value = err.data?.detail || t("settings.saveError");
    toast.error(saveError.value);
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  loadSettings();
  loadHardwareStatus();
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

      <!-- Hardware Transcoding Settings -->
      <div class="bg-gray-800 rounded-lg p-6">
        <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-4">
          <div>
            <h3 class="text-xl font-semibold text-white">
              {{ $t('settings.hardwareTranscoding.title') }}
            </h3>
          </div>
          <button
            @click="loadHardwareStatus(true)"
            :disabled="hardwareLoading || saving"
            class="px-4 py-2 text-sm font-medium text-white bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:cursor-not-allowed rounded-md transition-colors"
          >
            {{ hardwareLoading ? $t('common.loading') : $t('settings.hardwareTranscoding.refresh') }}
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.hardwareTranscoding.device') }}
            </label>
            <select
              v-model="selectedHardwareDevice"
              class="w-full px-4 py-2 bg-gray-700 text-white rounded-md border border-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              :disabled="saving"
            >
              <option v-for="option in hardwareDeviceOptions" :key="option.id" :value="option.id">
                {{ option.label }}
              </option>
            </select>
          </div>

          <div v-if="hardwareError" class="text-sm text-red-400">
            {{ hardwareError }}
          </div>

          <div v-else-if="hardwareStatus" class="space-y-3">
            <div v-if="hardwareStatus.devices.length === 0" class="text-sm text-gray-500">
              {{ $t('settings.hardwareTranscoding.noDevices') }}
            </div>

            <div v-for="device in hardwareStatus.devices" :key="device.id" class="border border-gray-700 rounded-md p-4">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div class="font-medium text-white">{{ device.name }}</div>
                  <div class="text-xs text-gray-500">{{ device.path || device.id }}</div>
                </div>
                <span
                  class="self-start rounded-full px-2 py-1 text-xs"
                  :class="device.available ? 'bg-green-900/50 text-green-300' : 'bg-gray-700 text-gray-400'"
                >
                  {{ device.available ? $t('common.enabled') : $t('common.disabled') }}
                </span>
              </div>
              <div v-if="device.capabilities.length" class="mt-3 flex flex-wrap gap-2">
                <span
                  v-for="capability in device.capabilities"
                  :key="`${device.id}-${capability.codec}`"
                  class="rounded-md bg-gray-700 px-2 py-1 text-xs text-gray-300"
                >
                  {{ capabilityLabel(capability) }}
                </span>
              </div>
              <div v-if="device.warnings.length" class="mt-3 space-y-1 text-xs text-yellow-300">
                <p v-for="warning in device.warnings" :key="warning">{{ warning }}</p>
              </div>
            </div>

            <div v-if="hardwareStatus.warnings.length" class="space-y-1 text-xs text-yellow-300">
              <p v-for="warning in hardwareStatus.warnings" :key="warning">{{ warning }}</p>
            </div>
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
  </div>
</template>
