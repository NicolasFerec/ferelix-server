<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type MediaCardInfo, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";

const props = defineProps<{ mediaFile: MediaCardInfo; returnTo?: string; sourceLibraryId?: number | string | null }>();
const { t } = useI18n();
const thumbnailFailed = ref(false);
const displayInfo = computed(() => getMediaTitleInfo(props.mediaFile.file_name));
const destination = computed(() => ({ name: "media-detail", params: { id: String(props.mediaFile.id) }, query: {...(props.sourceLibraryId ? { libraryId: String(props.sourceLibraryId) } : {}), ...(props.returnTo ? {returnTo:props.returnTo} : {})} }));
const progress = computed(() => {
  const view = props.mediaFile.user_view;
  const duration = view?.duration_seconds || props.mediaFile.duration;
  if (!view || !duration) return 0;
  return view.watched ? 100 : Math.min(100, Math.max(0, 100 * view.position_seconds / duration));
});
const durationLabel = computed(() => {
  const minutes = Math.floor((props.mediaFile.duration || 0) / 60);
  return minutes >= 60 ? t("mediaDetail.duration.hoursMinutes", { hours: Math.floor(minutes / 60), minutes: minutes % 60 }) : t("mediaDetail.duration.minutes", { minutes });
});
</script>

<template>
  <RouterLink :to="destination" class="media-card group block min-w-0 rounded-xl" :aria-label="displayInfo.title">
    <div class="relative aspect-video overflow-hidden rounded-xl border border-white/5 bg-surface transition-colors duration-200 group-hover:border-primary-400/60 group-focus-visible:border-primary-300">
      <img v-if="!thumbnailFailed" :src="media.getThumbnailUrl(mediaFile.id)" alt="" width="480" height="270" class="size-full object-cover" loading="lazy" decoding="async" @error="thumbnailFailed = true" />
      <div v-else class="flex size-full items-center justify-center bg-linear-to-br from-gray-800 to-background px-6 text-center text-sm font-medium text-muted">{{ displayInfo.title }}</div>
      <div class="pointer-events-none absolute inset-0 bg-black/20 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"></div>
      <span class="pointer-events-none absolute inset-0 flex items-center justify-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" aria-hidden="true">
        <span class="flex size-11 items-center justify-center rounded-full bg-white/95 text-background shadow-lg">
          <svg class="size-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 5v14l11-7z" /></svg>
        </span>
      </span>
      <span v-if="mediaFile.user_view?.watched" class="absolute right-2 top-2 rounded-md bg-black/75 px-2 py-1 text-[11px] text-gray-100">{{ $t('mediaDetail.watched') }}</span>
      <div v-if="progress > 0" role="progressbar" :aria-label="$t('mediaDetail.progress')" :aria-valuenow="Math.round(progress)" :aria-valuemin="0" :aria-valuemax="100" class="absolute inset-x-0 bottom-0 h-1.5 bg-gray-600">
        <div class="h-full min-w-0.5 bg-primary-400" :style="{ width: `${progress}%` }"></div>
      </div>
    </div>
    <h3 class="mt-3 truncate text-sm font-semibold text-gray-100 group-hover:text-white" :title="displayInfo.title">{{ displayInfo.title }}</h3>
    <p class="mt-1 flex gap-2 text-xs text-muted"><span v-if="displayInfo.year">{{ displayInfo.year }}</span><span v-if="displayInfo.year && mediaFile.duration" aria-hidden="true">·</span><span v-if="mediaFile.duration">{{ durationLabel }}</span></p>
  </RouterLink>
</template>
