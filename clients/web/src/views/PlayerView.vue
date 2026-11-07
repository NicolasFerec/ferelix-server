<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { type ItemDetail, items, type MediaFile, media } from "@/api/client";
import CustomVideoPlayer from "@/components/CustomVideoPlayer.vue";
import { usePlaybackCountdown } from "@/composables/usePlaybackCountdown";
import type { PlaybackRestoreState } from "@/composables/usePlayerPlayback";
import { useUser } from "@/composables/useUser";
import { safeReturnTo } from "@/services/authNavigation";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const { user, loadUser } = useUser();
const mediaFile = ref<MediaFile | null>(null);
const item = ref<ItemDetail | null>(null);
const loading = ref(false);
const error = ref("");
const reload = ref(0);
const playerVersion = ref(0);
const restoredState = ref<PlaybackRestoreState>();
const continuation = ref<Awaited<ReturnType<typeof items.continuation>> | null>(null);
const continuationLoading = ref(false);
const continuationError = ref("");
const navigating = ref(false);
let nextRequest: AbortController | undefined;
const countdown = usePlaybackCountdown(() => { void playNext(); });
const readyNext = computed(() => continuation.value?.status === "ready" && continuation.value.item && continuation.value.media_file_id ? continuation.value : null);

const seasonLocation = computed(() => {
  const source = continuation.value?.item ?? item.value;
  const seriesId = source?.series_id ?? item.value?.series_id;
  const seasonId = source?.parent_id ?? item.value?.parent_id;
  if (seriesId) return {name:"item-detail",params:{id:seriesId},query:seasonId ? {season:String(seasonId)} : {}};
  return seasonId ? {name:"item-detail",params:{id:seasonId}} : null;
});
function numberQueryValue(value: unknown): number | undefined {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (typeof rawValue !== "string") return undefined;
  const parsed = Number(rawValue);
  return Number.isFinite(parsed) ? parsed : undefined;
}
function positiveQuery(value: unknown): number | undefined {
  const parsed = numberQueryValue(value);
  return parsed !== undefined && Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}
function restorePlayer(state:PlaybackRestoreState) {
  cancelContinuation();
  restoredState.value=state;
  playerVersion.value++;
}
function cancelContinuation() {
  nextRequest?.abort();
  countdown.cancel();
  continuation.value = null;
  continuationError.value = "";
  continuationLoading.value = false;
}
watch(() => [route.params.id, route.query.item, reload.value], async (_, __, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  cancelContinuation();
  restoredState.value=undefined;
  mediaFile.value = null;
  item.value = null;
  loading.value = true;
  error.value = "";
  navigating.value = false;
  try {
    const result = await media.getMediaFile(Number(route.params.id), controller.signal);
    controller.signal.throwIfAborted();
    const itemId = positiveQuery(route.query.item) ?? result.item_id;
    const resolved = itemId ? await items.get(itemId, controller.signal) : await items.forFile(result.id, controller.signal);
    controller.signal.throwIfAborted();
    item.value = resolved;
    mediaFile.value = result;
  } catch {
    if (!controller.signal.aborted) error.value = t("player.error");
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}, { immediate: true });

async function handleEnded() {
  if (item.value?.kind !== "episode" || navigating.value) return;
  cancelContinuation();
  const controller = new AbortController();
  nextRequest = controller;
  const itemId = item.value.id;
  continuationLoading.value = true;
  try {
    const result = await items.continuation(itemId, "next", controller.signal);
    controller.signal.throwIfAborted();
    continuation.value = result;
    if (result.status === "ready" && result.item && result.media_file_id && user.value?.autoplay_next_episode === true) countdown.start();
  } catch {
    if (!controller.signal.aborted) continuationError.value = t("items.continuationFailed");
  } finally {
    if (!controller.signal.aborted) continuationLoading.value = false;
  }
}
async function playNext() {
  const target = readyNext.value;
  const from = item.value?.id;
  if (!target?.item || !target.media_file_id || !from || navigating.value) return;
  navigating.value = true;
  countdown.cancel();
  try {
    await router.replace({ name: "player", params: { id: target.media_file_id }, query: {
      item: String(target.item.id), position: String(target.position_seconds), continuationFrom: String(from), returnTo: safeReturnTo(route.query.returnTo),
    } });
  } finally { navigating.value = false; }
}
function handleClose() {
  cancelContinuation();
  if (route.query.returnTo) void router.push(safeReturnTo(route.query.returnTo));
  else router.back();
}
function handleEscape(event: KeyboardEvent) {
  if (event.key === "Escape") handleClose();
}
onMounted(() => { if (!user.value) void loadUser(); window.addEventListener("keydown", handleEscape); });
onUnmounted(() => { cancelContinuation(); window.removeEventListener("keydown", handleEscape); });
</script>

<template>
  <div class="player-view fixed inset-0 z-50 bg-black">
    <CustomVideoPlayer v-if="mediaFile" :key="`${mediaFile.id}/${item?.id}/${playerVersion}`" :restore-state="restoredState" :media-file="mediaFile"
      :item-id="item?.id" :initial-position-seconds="numberQueryValue(route.query.position)" :continuation-from-item-id="positiveQuery(route.query.continuationFrom)"
      :initial-video-stream-index="numberQueryValue(route.query.video)" :initial-audio-stream-index="numberQueryValue(route.query.audio)"
      :initial-subtitle-stream-index="numberQueryValue(route.query.subtitle)" @close="handleClose" @ended="handleEnded" @activity="cancelContinuation" @restore="restorePlayer" />
    <div v-else-if="loading" role="status" class="flex h-full items-center justify-center text-white"><p>{{ $t('player.loading') }}</p></div>
    <div v-else-if="error" role="alert" class="flex h-full flex-col items-center justify-center gap-5 p-6 text-white">
      <p>{{ error }}</p><div class="flex gap-3"><button type="button" class="button-primary" @click="reload++">{{ $t('player.retry') }}</button><button type="button" class="button-secondary" @click="handleClose">{{ $t('player.close') }}</button></div>
    </div>
    <section v-if="continuation || continuationLoading || continuationError" :aria-label="$t('items.nextEpisode')" class="absolute inset-x-5 bottom-28 z-50 ml-auto max-w-md rounded-sm bg-surface/95 p-5 shadow-xl sm:right-8">
      <p v-if="continuationLoading" role="status" class="text-sm text-muted">{{ $t('common.loading') }}</p>
      <template v-else-if="readyNext">
        <p class="text-xs uppercase tracking-widest text-muted">{{ $t('items.nextEpisode') }}</p><h2 class="mt-2 text-lg font-semibold">{{ readyNext.item?.title }}</h2>
        <p v-if="countdown.active.value" role="status" class="mt-3 text-sm text-muted">{{ $t('items.nextCountdown', { seconds: countdown.remaining.value }) }}</p>
        <div class="mt-5 flex flex-wrap gap-3"><button type="button" :disabled="navigating" class="button-primary" @click="playNext">{{ $t('items.playNext') }}</button><button type="button" class="button-secondary" @click="cancelContinuation">{{ $t('common.cancel') }}</button></div>
      </template>
      <template v-else><p v-if="continuationError" role="alert" class="text-sm text-red-200">{{ continuationError }}</p><p v-else-if="continuation" class="text-sm text-muted">{{ $t(`items.continuation.${continuation.status}`) }}<span v-if="continuation.item"> · {{ continuation.item.title }}</span></p><div class="mt-4 flex gap-3"><button v-if="continuationError" type="button" class="button-secondary" @click="handleEnded">{{ $t('common.retry') }}</button><button type="button" class="button-secondary" @click="cancelContinuation">{{ $t('items.dismissContinuation') }}</button></div></template>
      <RouterLink v-if="seasonLocation" :to="seasonLocation" class="mt-5 inline-flex text-sm text-primary-300">{{ $t('items.openSeason') }} →</RouterLink>
    </section>
  </div>
</template>
