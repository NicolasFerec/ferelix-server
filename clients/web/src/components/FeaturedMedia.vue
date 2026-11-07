<script setup lang="ts">
import { computed, ref } from "vue";
import { type MediaCardInfo, media } from "@/api/client";
import { getMediaTitleInfo } from "@/services/mediaDisplay";

const props = defineProps<{ item: MediaCardInfo }>();
const title = computed(() => getMediaTitleInfo(props.item.file_name).title);
const thumbnailFailed = ref(false);
const canResume = computed(() => !!props.item.user_view && !props.item.user_view.watched && props.item.user_view.position_seconds >= 10);
</script>

<template>
  <section class="relative mb-10 flex min-h-[340px] overflow-hidden rounded-2xl border border-outline bg-surface sm:min-h-[420px]" :aria-label="title">
    <img v-if="!thumbnailFailed" :src="media.getThumbnailUrl(item.id)" alt="" width="1280" height="720" fetchpriority="high" class="absolute inset-0 size-full object-cover" @error="thumbnailFailed = true" />
    <div class="absolute inset-0 bg-linear-to-r from-black/95 via-black/65 to-black/15"></div>
    <div class="absolute inset-0 bg-linear-to-t from-black/70 to-transparent"></div>
    <div class="relative flex max-w-2xl flex-col justify-end p-7 sm:p-12">
      <p class="mb-4 text-xs font-semibold uppercase tracking-[.22em] text-primary-200">{{ canResume ? $t('home.continueWatching') : $t('home.inYourLibrary') }}</p>
      <h1 class="mb-7 text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">{{ title }}</h1>
      <div class="flex flex-wrap gap-3">
        <RouterLink :to="{ name: 'player', params: { id: item.id } }" class="button-primary"><svg aria-hidden="true" class="size-4" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2.5v11L13 8z" /></svg>{{ canResume ? $t('mediaDetail.resume') : $t('mediaDetail.play') }}</RouterLink>
        <RouterLink :to="{ name: 'media-detail', params: { id: item.id } }" class="button-secondary bg-white/10 backdrop-blur-sm">{{ $t('home.details') }}</RouterLink>
      </div>
    </div>
  </section>
</template>
