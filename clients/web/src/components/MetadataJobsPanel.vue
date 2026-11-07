<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type MetadataJob, metadata } from "@/api/client";

const { t, te, locale } = useI18n();
const jobs = ref<MetadataJob[]>([]);
const status = ref("");
const page = ref(1);
const revision = ref(0);
const loading = ref(false);
const error = ref("");
const hasNext = ref(false);
let request: AbortController | undefined;
const statuses = ["pending", "running", "done", "failed", "cancelled", "needs_identification"];
watch(status, () => { page.value = 1; });
watch(() => [status.value, page.value, revision.value], async (_, __, onCleanup) => {
  const controller = new AbortController(); request = controller; onCleanup(() => controller.abort());
  loading.value = true; error.value = "";
  try {
    const result = await metadata.jobs(status.value || undefined, (page.value - 1) * 48, 49, controller.signal);
    controller.signal.throwIfAborted(); jobs.value = result.slice(0, 48); hasNext.value = result.length > 48;
  } catch { if (!controller.signal.aborted) error.value = t("metadata.jobsFailed"); }
  finally { if (!controller.signal.aborted) loading.value = false; }
}, { immediate: true });
function date(value: string) {
  const parsed = new Date(value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat(locale.value, { dateStyle: "short", timeStyle: "short" }).format(parsed);
}
onUnmounted(() => request?.abort());
</script>

<template>
  <section class="mt-10 border-t border-outline pt-8">
    <header class="mb-6 flex flex-wrap items-center justify-between gap-4"><h2 class="text-xl font-semibold">{{ $t('metadata.jobs') }}</h2><button type="button" class="button-secondary" :disabled="loading" @click="revision++">{{ $t('common.refresh') }}</button></header>
    <label class="mb-5 block max-w-xs space-y-2"><span class="field-label">{{ $t('metadata.status') }}</span><select v-model="status" class="field-input"><option value="">{{ $t('metadata.allJobs') }}</option><option v-for="value in statuses" :key="value" :value="value">{{ $t(`metadata.jobStatus.${value}`) }}</option></select></label>
    <p v-if="loading" role="status" class="empty-state">{{ $t('common.loading') }}</p>
    <p v-else-if="error" role="alert" class="form-error">{{ error }}</p>
    <p v-else-if="!jobs.length" class="empty-state">{{ $t('metadata.noJobs') }}</p>
    <ul v-else class="divide-y divide-outline"><li v-for="job in jobs" :key="job.id" class="space-y-2 py-4"><div class="flex flex-wrap items-center justify-between gap-3"><RouterLink :to="`/items/${job.item_id}`" class="text-sm text-primary-300">{{ $t('metadata.jobItem', { id: job.item_id }) }}</RouterLink><span class="text-xs text-muted">{{ te(`metadata.jobStatus.${job.status}`) ? $t(`metadata.jobStatus.${job.status}`) : job.status }} · {{ date(job.updated_at) }}</span></div><p v-if="job.error" class="break-words text-sm text-red-200">{{ job.error }}</p><p class="text-xs text-muted">{{ $t('metadata.attempts', { count: job.attempts }) }}</p></li></ul>
    <nav v-if="page > 1 || hasNext" class="mt-6 flex justify-between gap-4" :aria-label="$t('library.pagination')"><button type="button" class="button-secondary" :disabled="loading || page===1" @click="page--">{{ $t('common.previous') }}</button><button type="button" class="button-secondary" :disabled="loading || !hasNext" @click="page++">{{ $t('common.next') }}</button></nav>
  </section>
</template>
