<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { jobs as jobsApi } from "@/api/client";

const { t, locale } = useI18n();

const jobs = ref([]);
const jobHistory = ref([]);
const loading = ref(false);
const error = ref("");
const triggeringJobs = ref(new Set());
const cancellingJobs = ref(new Set());
const showSuccess = ref(false);
const showError = ref(false);
const successMessage = ref("");
const errorMessage = ref("");
let pollInterval = null;

// Date formatter using browser's Intl API
function formatDate(dateString) {
  if (!dateString) {
    return t("jobs.neverRun");
  }

  try {
    const date = new Date(dateString);
    // Use browser's locale for date/time formatting
    const formatter = new Intl.DateTimeFormat(locale.value, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    return formatter.format(date);
  } catch (err) {
    console.error("Failed to format date:", err);
    return dateString;
  }
}

function getJobName(job) {
  // For scan library jobs, prefer the fallback name which includes library name
  if (job?.name_key === "jobs.names.scan_library" && job?.name) {
    return job.name;
  }

  if (job?.name_key) {
    const translated = t(job.name_key);
    if (translated && translated !== job.name_key) {
      return translated;
    }
  }
  return job?.name || job?.id || "";
}

function getHistoryJobName(record) {
  // For scan library jobs, extract library name/ID and format with translated base name
  // Note: library name itself should NOT be translated, only the base "Library Scanner" part
  if (record?.name_key === "jobs.names.scan_library" && record?.job_name) {
    // Extract library identifier from job_name (format: "Library Scanner: {name_or_id}")
    // This works for both English "Library Scanner: Films" and other languages
    const match = record.job_name.match(/^Library Scanner:\s*(.+)$/);
    if (match) {
      const libraryIdentifier = match[1]; // Keep library name as-is, don't translate
      const translatedBase = t(record.name_key);
      return `${translatedBase}: ${libraryIdentifier}`;
    }
    // Also try to match if it's already in translated format (e.g., "Analyseur de bibliothèque: Films")
    const translatedMatch = record.job_name.match(/^(.+?):\s*(.+)$/);
    if (translatedMatch) {
      // Already has translated format, return as-is
      return record.job_name;
    }
    // Fallback: use the job_name as-is if pattern doesn't match
    return record.job_name;
  }

  if (record?.name_key) {
    const translated = t(record.name_key);
    if (translated && translated !== record.name_key) {
      return translated;
    }
  }
  return record?.job_name || record?.job_id || "";
}

function truncatePath(path, maxLength = 50) {
  if (!path || path.length <= maxLength) {
    return path;
  }
  const parts = path.split("/");
  if (parts.length <= 2) {
    return `${path.substring(0, maxLength)}...`;
  }
  // Keep first and last parts, truncate middle
  return `${parts[0]}/.../${parts[parts.length - 1]}`;
}

function getStatusLabel(status) {
  switch (status) {
    case "running":
      return t("jobs.status.running");
    case "success":
      return t("jobs.status.success");
    case "failed":
      return t("jobs.status.failed");
    case "cancelled":
      return t("jobs.status.cancelled");
    default:
      return t("jobs.status.pending");
  }
}

function getStatusClass(status) {
  switch (status) {
    case "running":
      return "bg-blue-100 text-blue-800";
    case "success":
      return "bg-green-100 text-green-800";
    case "failed":
      return "bg-red-100 text-red-800";
    case "cancelled":
      return "bg-orange-100 text-orange-800";
    default:
      return "bg-yellow-100 text-yellow-800";
  }
}

function getHistoryStatusClass(status) {
  switch (status) {
    case "running":
      return "bg-blue-100 text-blue-800";
    case "completed":
      return "bg-green-100 text-green-800";
    case "failed":
      return "bg-red-100 text-red-800";
    case "cancelled":
      return "bg-orange-100 text-orange-800";
    default:
      return "bg-gray-100 text-gray-800";
  }
}

function getHistoryStatusLabel(status) {
  switch (status) {
    case "running":
      return t("jobs.status.running");
    case "completed":
      return t("jobs.status.completed");
    case "failed":
      return t("jobs.status.failed");
    case "cancelled":
      return t("jobs.status.cancelled");
    default:
      return status;
  }
}

function getJobTypeLabel(type) {
  if (type === "scheduled") {
    return t("jobs.type.scheduled");
  } else if (type === "one-off") {
    return t("jobs.type.oneOff");
  }
  return type;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }

  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  } else if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  } else {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  }
}

function addTriggering(jobId) {
  const next = new Set(triggeringJobs.value);
  next.add(jobId);
  triggeringJobs.value = next;
}

function removeTriggering(jobId) {
  const next = new Set(triggeringJobs.value);
  next.delete(jobId);
  triggeringJobs.value = next;
}

function addCancelling(jobId) {
  const next = new Set(cancellingJobs.value);
  next.add(jobId);
  cancellingJobs.value = next;
}

function removeCancelling(jobId) {
  const next = new Set(cancellingJobs.value);
  next.delete(jobId);
  cancellingJobs.value = next;
}

async function loadJobs(showLoading = true) {
  if (showLoading) {
    loading.value = true;
  }
  error.value = "";
  try {
    jobs.value = await jobsApi.getJobs();
  } catch (err) {
    console.error("Failed to load jobs:", err);
    error.value = err.data?.detail || t("jobs.loadFailed");
  } finally {
    if (showLoading) {
      loading.value = false;
    }
  }
}

async function loadJobHistory(showLoading = true) {
  if (showLoading) {
    loading.value = true;
  }
  error.value = "";
  try {
    jobHistory.value = await jobsApi.getJobHistory();
  } catch (err) {
    console.error("Failed to load job history:", err);
    // Don't set error for history failures, just log
  } finally {
    if (showLoading) {
      loading.value = false;
    }
  }
}

async function loadAll(showLoading = true) {
  if (showLoading) {
    loading.value = true;
  }
  error.value = "";
  try {
    await Promise.all([loadJobs(false), loadJobHistory(false)]);
  } catch (err) {
    console.error("Failed to load data:", err);
    error.value = err.data?.detail || t("jobs.loadFailed");
  } finally {
    if (showLoading) {
      loading.value = false;
    }
  }
}

function startPolling() {
  // Poll every 2 seconds for job updates
  if (pollInterval) {
    return;
  }
  pollInterval = setInterval(() => {
    loadJobs(false); // Don't show loading spinner on polling updates
    loadJobHistory(false);
  }, 2000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

async function triggerJob(jobId) {
  addTriggering(jobId);
  showSuccess.value = false;
  showError.value = false;

  try {
    await jobsApi.triggerJob(jobId);
    // Reload jobs to get updated status
    await loadJobs();
    successMessage.value = t("jobs.triggerSuccess");
    showSuccess.value = true;

    // Hide success message after 3 seconds
    setTimeout(() => {
      showSuccess.value = false;
    }, 3000);
  } catch (err) {
    console.error("Failed to trigger job:", err);
    errorMessage.value = err.data?.detail || t("jobs.triggerFailed");
    showError.value = true;

    // Hide error message after 5 seconds
    setTimeout(() => {
      showError.value = false;
    }, 5000);
  } finally {
    removeTriggering(jobId);
  }
}

async function cancelJob(jobId) {
  addCancelling(jobId);
  showSuccess.value = false;
  showError.value = false;

  try {
    await jobsApi.cancelJob(jobId);
    // Reload jobs to get updated status
    await loadJobs();
    successMessage.value = t("jobs.cancelSuccess");
    showSuccess.value = true;

    // Hide success message after 3 seconds
    setTimeout(() => {
      showSuccess.value = false;
    }, 3000);
  } catch (err) {
    console.error("Failed to cancel job:", err);
    errorMessage.value = err.data?.detail || t("jobs.cancelFailed");
    showError.value = true;

    // Hide error message after 5 seconds
    setTimeout(() => {
      showError.value = false;
    }, 5000);
  } finally {
    removeCancelling(jobId);
  }
}

onMounted(() => {
  loadAll();
  startPolling();
});

onBeforeUnmount(() => {
  stopPolling();
});
</script>

<template>
  <div class="jobs-panel">
    <div class="flex justify-between items-center mb-6">
      <h2 class="text-2xl font-semibold text-white">{{ $t('jobs.title') }}</h2>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center text-gray-400 py-12">
      {{ $t('common.loading') }}
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="text-center text-red-400 py-12">
      <p>{{ error }}</p>
      <button
        @click="loadAll()"
        class="mt-4 px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ $t('common.retry') }}
      </button>
    </div>

    <!-- Scheduled Jobs Section -->
    <div v-else class="mb-8">
      <h3 class="text-xl font-semibold text-white mb-4">{{ $t('jobs.scheduled') }}</h3>

      <!-- Empty state -->
      <div v-if="jobs.length === 0" class="text-center text-gray-400 py-12 bg-gray-800 rounded-lg">
        <p>{{ $t('jobs.noJobs') }}</p>
      </div>

      <!-- Jobs table -->
      <div v-else class="bg-gray-800 rounded-lg overflow-hidden">
        <table class="min-w-full divide-y divide-gray-700">
          <thead class="bg-gray-700">
            <tr>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.name') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.lastRun') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.nextRun') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.statusLabel') }}
              </th>
              <th
                class="px-6 py-3 text-right text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.actions') }}
              </th>
            </tr>
          </thead>
          <tbody class="bg-gray-800 divide-y divide-gray-700">
            <tr v-for="job in jobs" :key="job.id" class="hover:bg-gray-750">
              <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
                {{ getJobName(job) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                {{ formatDate(job.last_run_time) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                {{ formatDate(job.next_run_time) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span
                  :class="[
                    'px-2 inline-flex text-xs leading-5 font-semibold rounded-full',
                    getStatusClass(job.status),
                  ]"
                >
                  {{ getStatusLabel(job.status) }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <button
                  @click="triggerJob(job.id)"
                  :disabled="triggeringJobs.has(job.id)"
                  class="px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-md transition-colors text-sm"
                >
                  {{ triggeringJobs.has(job.id) ? $t('jobs.triggering') : $t('jobs.trigger') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Job History Section -->
    <div>
      <h3 class="text-xl font-semibold text-white mb-4">{{ $t('jobs.history') }}</h3>

      <!-- Empty state -->
      <div
        v-if="jobHistory.length === 0"
        class="text-center text-gray-400 py-12 bg-gray-800 rounded-lg"
      >
        <p>{{ $t('jobs.noHistory') }}</p>
      </div>

      <!-- History table -->
      <div v-else class="bg-gray-800 rounded-lg overflow-hidden">
        <table class="min-w-full divide-y divide-gray-700">
          <thead class="bg-gray-700">
            <tr>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.name') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.typeLabel') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.startedAt') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.duration') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.progress') }}
              </th>
              <th
                class="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider"
              >
                {{ $t('jobs.statusLabel') }}
              </th>
            </tr>
          </thead>
          <tbody class="bg-gray-800 divide-y divide-gray-700">
            <tr v-for="record in jobHistory" :key="record.job_id" class="hover:bg-gray-750">
              <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
                {{ getHistoryJobName(record) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                <span class="px-2 py-1 rounded-sm text-xs bg-gray-700 text-gray-300">
                  {{ getJobTypeLabel(record.job_type) }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                {{ formatDate(record.started_at) }}
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
                {{ formatDuration(record.duration_seconds) }}
              </td>
              <td class="px-6 py-4 text-sm">
                <div v-if="record.files_total">
                  <div class="text-gray-300 mb-1">
                    {{ record.files_processed || 0 }} / {{ record.files_total }}
                    {{ $t('jobs.files') }}
                  </div>
                  <div class="w-full bg-gray-700 rounded-full h-2">
                    <div
                      class="bg-primary-600 h-2 rounded-full transition-all duration-300"
                      :style="{
                        width: ((record.files_processed || 0) / record.files_total) * 100 + '%',
                      }"
                    ></div>
                  </div>
                </div>
                <span v-else class="text-gray-500">-</span>
              </td>
              <td class="px-6 py-4">
                <div class="flex items-center justify-between">
                  <div>
                    <span
                      :class="[
                        'px-2 inline-flex text-xs leading-5 font-semibold rounded-full',
                        getHistoryStatusClass(record.status),
                      ]"
                    >
                      {{ getHistoryStatusLabel(record.status) }}
                    </span>
                    <div v-if="record.error" class="mt-1 text-xs text-red-400">
                      {{ record.error }}
                    </div>
                  </div>
                  <button
                    v-if="record.status === 'running'"
                    @click="cancelJob(record.job_id)"
                    :disabled="cancellingJobs.has(record.job_id)"
                    class="ml-4 px-3 py-1 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-md transition-colors text-xs"
                  >
                    {{
                      cancellingJobs.has(record.job_id) ? $t('jobs.cancelling') : $t('jobs.cancel')
                    }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Success notification -->
    <div
      v-if="showSuccess"
      class="fixed top-4 right-4 bg-green-600 text-white px-6 py-3 rounded-md shadow-lg z-50"
    >
      {{ successMessage }}
    </div>

    <!-- Error notification -->
    <div
      v-if="showError"
      class="fixed top-4 right-4 bg-red-600 text-white px-6 py-3 rounded-md shadow-lg z-50"
    >
      {{ errorMessage }}
    </div>
  </div>
</template>
