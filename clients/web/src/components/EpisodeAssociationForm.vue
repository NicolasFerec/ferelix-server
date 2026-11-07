<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type ItemCard, items, type MetadataItem, metadata } from "@/api/client";

const props = defineProps<{ item: MetadataItem }>();
const emit = defineEmits<{ associated: [itemId: number]; busy: [value: boolean]; conflict: [] }>();
const { t } = useI18n();
const query = ref("");
const series = ref<ItemCard[]>([]);
const seriesId = ref("");
const seasonId = ref("");
const episodeId = ref("");
const seasons = ref<ItemCard[]>([]);
const episodes = ref<ItemCard[]>([]);
const target = ref<MetadataItem | null>(null);
const page = ref(1);
const seriesMore = ref(false);
const seasonsMore = ref(false);
const episodesMore = ref(false);
const searching = ref(false);
const searched = ref(false);
const loadingSeasons = ref(false);
const loadingEpisodes = ref(false);
const loadingTarget = ref(false);
const pending = ref(false);
const error = ref("");
const lifetime = new AbortController();
let searchRequest: AbortController | undefined;
let seasonRequest: AbortController | undefined;
let episodeRequest: AbortController | undefined;

async function search(targetPage = 1) {
  if (!query.value.trim()) return;
  searchRequest?.abort();
  const controller = new AbortController(); searchRequest = controller;
  const signal = AbortSignal.any([controller.signal, lifetime.signal]);
  searching.value = true; searched.value = false; error.value = "";
  seriesId.value = "";
  page.value = targetPage;
  try {
    const result = await items.list({ kind: "series", q: query.value.trim(), library_id: props.item.metadata_library_id ?? undefined, skip: (targetPage - 1) * 20, limit: 21 }, signal);
    signal.throwIfAborted();
    series.value = result.slice(0, 20); seriesMore.value = result.length > 20; searched.value = true;
  } catch { if (!signal.aborted) error.value = t("items.loadFailed"); }
  finally { if (!signal.aborted) searching.value = false; }
}
async function loadSeasons(append = false) {
  seasonRequest?.abort();
  const controller = new AbortController(); seasonRequest = controller;
  const signal = AbortSignal.any([controller.signal, lifetime.signal]);
  if (!seriesId.value) { seasons.value = []; seasonsMore.value = false; loadingSeasons.value = false; return; }
  loadingSeasons.value = true; error.value = "";
  try {
    const result = await items.list({ parent_id: Number(seriesId.value), kind: "season", skip: append ? seasons.value.length : 0, limit: 49 }, signal);
    signal.throwIfAborted();
    seasons.value = append ? [...seasons.value, ...result.slice(0, 48)] : result.slice(0, 48); seasonsMore.value = result.length > 48;
  } catch { if (!signal.aborted) error.value = t("items.loadFailed"); }
  finally { if (!signal.aborted) loadingSeasons.value = false; }
}
async function loadEpisodes(append = false) {
  episodeRequest?.abort();
  const controller = new AbortController(); episodeRequest = controller;
  const signal = AbortSignal.any([controller.signal, lifetime.signal]);
  if (!seasonId.value) { episodes.value = []; episodesMore.value = false; loadingEpisodes.value = false; return; }
  loadingEpisodes.value = true; error.value = "";
  try {
    const result = await items.list({ parent_id: Number(seasonId.value), kind: "episode", skip: append ? episodes.value.length : 0, limit: 49 }, signal);
    signal.throwIfAborted();
    episodes.value = append ? [...episodes.value, ...result.slice(0, 48)] : result.slice(0, 48); episodesMore.value = result.length > 48;
  } catch { if (!signal.aborted) error.value = t("items.loadFailed"); }
  finally { if (!signal.aborted) loadingEpisodes.value = false; }
}
watch(seriesId, () => { seasonId.value = ""; episodeId.value = ""; void loadSeasons(); });
watch(seasonId, () => { episodeId.value = ""; void loadEpisodes(); });
watch(episodeId, async (id, _, onCleanup) => {
  const controller = new AbortController(); onCleanup(() => controller.abort());
  const signal = AbortSignal.any([controller.signal, lifetime.signal]);
  target.value = null; error.value = ""; loadingTarget.value = false;
  if (!id) return;
  loadingTarget.value = true;
  try { const result = await metadata.get(Number(id), signal); signal.throwIfAborted(); target.value = result; }
  catch { if (!signal.aborted) error.value = t("items.loadFailed"); }
  finally { if (!signal.aborted) loadingTarget.value = false; }
});
async function associate() {
  if (!target.value || pending.value) return;
  pending.value = true; emit("busy", true); error.value = "";
  try {
    const result = await metadata.associateEpisode(props.item.id, props.item.revision, target.value.id, target.value.revision);
    if (!lifetime.signal.aborted) emit("associated", result.item_id);
  } catch (cause) {
    if (!lifetime.signal.aborted) {
      error.value = cause && typeof cause === "object" && "status" in cause && cause.status === 409 ? t("metadata.conflict") : t("metadata.associationFailed");
      if (cause && typeof cause === "object" && "status" in cause && cause.status === 409) emit("conflict");
      target.value = null;
    }
  } finally { pending.value = false; emit("busy", false); }
}
onUnmounted(() => lifetime.abort());
</script>

<template>
  <section class="space-y-4">
    <h3 class="font-semibold">{{ $t('metadata.associateEpisode') }}</h3>
    <p class="text-sm leading-6 text-muted">{{ $t('metadata.associationHelp') }}</p>
    <form class="flex flex-wrap gap-3" @submit.prevent="search()">
      <label for="association-query" class="sr-only">{{ $t('metadata.findSeries') }}</label>
      <input id="association-query" v-model="query" class="field-input min-w-0 flex-1" type="search" required maxlength="200" :placeholder="$t('metadata.findSeries')" />
      <button type="submit" :disabled="searching || pending" class="button-secondary">{{ $t('discovery.action') }}</button>
    </form>
    <p v-if="searching || loadingSeasons || loadingEpisodes || loadingTarget" role="status" class="text-sm text-muted">{{ $t('common.loading') }}</p>
    <p v-if="searched && !series.length" class="text-sm text-muted">{{ $t('metadata.noMatches') }}</p>
    <label v-if="series.length" class="block space-y-2"><span class="field-label">{{ $t('items.kind.series') }}</span><select v-model="seriesId" class="field-input" :disabled="searching || pending"><option value="">{{ $t('metadata.chooseSeries') }}</option><option v-for="row in series" :key="row.id" :value="String(row.id)">{{ row.title }}{{ row.year ? ` (${row.year})` : '' }}</option></select></label>
    <div v-if="page>1 || seriesMore" class="flex justify-between gap-3"><button type="button" class="button-secondary" :disabled="page===1 || searching || pending" @click="search(page-1)">{{ $t('common.previous') }}</button><button type="button" class="button-secondary" :disabled="!seriesMore || searching || pending" @click="search(page+1)">{{ $t('common.next') }}</button></div>
    <label v-if="seriesId && !loadingSeasons" class="block space-y-2"><span class="field-label">{{ $t('items.kind.season') }}</span><select v-model="seasonId" class="field-input" :disabled="!seasons.length || pending"><option value="">{{ $t(seasons.length ? 'metadata.chooseSeason' : 'items.hierarchyPending') }}</option><option v-for="row in seasons" :key="row.id" :value="String(row.id)">{{ row.title }}</option></select></label>
    <button v-if="seasonsMore" type="button" class="button-secondary" :disabled="loadingSeasons || pending" @click="loadSeasons(true)">{{ $t('items.moreSeasons') }}</button>
    <label v-if="seasonId && !loadingEpisodes" class="block space-y-2"><span class="field-label">{{ $t('items.kind.episode') }}</span><select v-model="episodeId" class="field-input" :disabled="!episodes.length || pending"><option value="">{{ $t(episodes.length ? 'metadata.chooseEpisode' : 'items.hierarchyPending') }}</option><option v-for="row in episodes" :key="row.id" :value="String(row.id)" :disabled="row.id===item.id">{{ $t('items.episodeNumber',{season:row.season_number ?? '?',episode:row.episode_number ?? '?'}) }} · {{ row.title }}{{ row.availability==='missing' ? ` · ${$t('items.availability.missing')}` : '' }}</option></select></label>
    <button v-if="episodesMore" type="button" class="button-secondary" :disabled="loadingEpisodes || pending" @click="loadEpisodes(true)">{{ $t('metadata.moreEpisodes') }}</button>
    <div v-if="target" class="space-y-4 rounded-sm border border-outline p-4"><p class="text-sm leading-6">{{ $t('metadata.associationConfirm',{source:item.title,target:target.title,season:target.season_number ?? '?',episode:target.episode_number ?? '?'}) }}</p><button type="button" :disabled="pending" class="button-primary" @click="associate">{{ $t('metadata.associateAction') }}</button></div>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
  </section>
</template>
