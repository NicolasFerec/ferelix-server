<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { items, type MediaCardInfo, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";
import WatchStateMenu from "./WatchStateMenu.vue";

const props = defineProps<{ mediaFile: MediaCardInfo; returnTo?: string; sourceLibraryId?: number | string | null; hideWatchActions?: boolean }>();
const emit=defineEmits<{changed:[]}>();
const { t } = useI18n();
const thumbnailFailed = ref(false);
const displayInfo = computed(() => props.mediaFile.title ? {title:props.mediaFile.title,year:props.mediaFile.year} : getMediaTitleInfo(props.mediaFile.file_name));
const destination = computed(() => ({ name: props.mediaFile.item_id ? "item-detail" : "media-detail", params: { id: String(props.mediaFile.item_id || props.mediaFile.id) }, query: {...(props.sourceLibraryId ? { libraryId: String(props.sourceLibraryId) } : {}), ...(props.returnTo ? {returnTo:props.returnTo} : {})} }));
const progress = computed(() => {
  const view = props.mediaFile.user_view;
  const duration = view?.duration_seconds || props.mediaFile.duration;
  if (!view || !duration || view.resume_active === false) return 0;
  return Math.min(100, Math.max(0, 100 * view.position_seconds / duration));
});
const durationLabel = computed(() => {
  const minutes = Math.floor((props.mediaFile.duration || 0) / 60);
  return minutes >= 60 ? t("mediaDetail.duration.hoursMinutes", { hours: Math.floor(minutes / 60), minutes: minutes % 60 }) : t("mediaDetail.duration.minutes", { minutes });
});
</script>

<template>
  <article class="relative min-w-0">
  <RouterLink :to="destination" class="media-card group block min-w-0 rounded-sm" :aria-label="(mediaFile.watched ?? mediaFile.user_view?.watched) ? `${displayInfo.title} · ${$t('mediaDetail.watched')}` : displayInfo.title">
    <div class="relative aspect-2/3 overflow-hidden rounded-sm bg-surface">
      <img v-if="!thumbnailFailed" :src="items.artworkUrl(mediaFile.poster_url) || media.getThumbnailUrl(mediaFile.id)" alt="" width="480" height="720" class="size-full object-cover" loading="lazy" decoding="async" @error="thumbnailFailed = true" />
      <div v-else class="flex size-full items-center justify-center bg-linear-to-br from-gray-800 to-background px-6 text-center text-sm font-medium text-muted">{{ displayInfo.title }}</div>
      <div class="pointer-events-none absolute inset-0 bg-black/20 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"></div>
      <span class="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" aria-hidden="true">
        <span class="flex size-11 items-center justify-center rounded-full bg-white/95 text-background shadow-lg">
          <svg class="size-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 5v14l11-7z" /></svg>
        </span>
      </span>
      <span v-if="mediaFile.watched ?? mediaFile.user_view?.watched" role="img" :aria-label="$t('mediaDetail.watched')" class="absolute right-2 top-2 flex size-6 items-center justify-center rounded-full bg-black/70 text-gray-100"><svg aria-hidden="true" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m5 12 4 4L19 6" /></svg></span>
      <div v-if="progress > 0" role="progressbar" :aria-label="$t('mediaDetail.progress')" :aria-valuenow="Math.round(progress)" :aria-valuemin="0" :aria-valuemax="100" class="absolute inset-x-0 bottom-0 h-1.5 bg-black/30">
        <div class="h-full min-w-0.5 bg-white/45" :style="{ width: `${progress}%` }"></div>
      </div>
    </div>
    <h3 class="mt-3 truncate text-sm font-semibold text-gray-100 group-hover:text-white" :title="displayInfo.title" :class="{ 'pr-10': mediaFile.item_id && !hideWatchActions }">{{ displayInfo.title }}</h3>
    <p class="mt-1 flex gap-2 text-xs text-muted" :class="{ 'pr-10': mediaFile.item_id && !hideWatchActions }"><span v-if="displayInfo.year">{{ displayInfo.year }}</span><span v-if="displayInfo.year && mediaFile.duration" aria-hidden="true">·</span><span v-if="mediaFile.duration">{{ durationLabel }}</span></p>
  </RouterLink>
  <div v-if="mediaFile.item_id && !hideWatchActions" class="absolute bottom-0 right-0"><WatchStateMenu :item-id="mediaFile.item_id" kind="movie" :watched="mediaFile.watched ?? mediaFile.user_view?.watched ?? false" :state-revision="mediaFile.state_revision ?? 0" @changed="emit('changed')" /></div>
  </article>
</template>
