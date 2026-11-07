<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type ItemCard as Card, items } from "@/api/client";
import WatchStateMenu from "@/components/WatchStateMenu.vue";
import { formatReleaseDate } from "@/services/mediaDisplay";

const {locale}=useI18n();
const props=defineProps<{item:Card;returnTo?:string}>();
const emit=defineEmits<{changed:[]}>();
const failed=ref(false);
const poster=computed(()=>failed.value ? null : items.artworkUrl(props.item.poster_url));
const progress=computed(()=>Math.min(100,Math.max(0,props.item.progress_percent || 0)));
const destination=computed(()=>({name:"item-detail",params:{id:String(props.item.id)},query:props.returnTo ? {returnTo:props.returnTo} : {}}));
</script>

<template>
  <article class="item-card relative min-w-0">
    <RouterLink :to="destination" class="group block rounded-sm" :aria-label="item.watched ? `${item.title} · ${$t('mediaDetail.watched')}` : item.title">
      <div class="relative aspect-2/3 overflow-hidden rounded-sm bg-surface">
        <img v-if="poster" :src="poster" alt="" width="480" height="720" loading="lazy" decoding="async" class="size-full object-cover" @error="failed=true" />
        <div v-else class="flex size-full items-center justify-center bg-linear-to-br from-gray-800 to-background px-5 text-center text-sm text-muted">{{ item.title }}</div>
        <span v-if="item.availability !== 'available'" class="absolute left-2 top-2 max-w-[calc(100%-3.5rem)] rounded-sm bg-black/75 px-2 py-1 text-xs text-gray-200">{{ $t(`items.availability.${item.availability}`) }}</span>
        <span v-if="item.watched" role="img" :aria-label="$t('mediaDetail.watched')" class="absolute right-2 top-2 flex size-6 items-center justify-center rounded-full bg-black/70 text-gray-100"><svg aria-hidden="true" class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m5 12 4 4L19 6" /></svg></span>
        <div v-if="progress>0 && item.resume_active" role="progressbar" :aria-label="$t('mediaDetail.progress')" :aria-valuenow="Math.round(progress)" :aria-valuemin="0" :aria-valuemax="100" class="absolute inset-x-0 bottom-0 h-1.5 bg-black/30"><div class="h-full min-w-0.5 bg-white/45" :style="{width:`${progress}%`}"></div></div>
      </div>
      <h3 class="mt-3 truncate pr-10 text-sm font-semibold" :title="item.title">{{ item.title }}</h3>
      <p class="mt-1 pr-10 text-xs text-muted"><template v-if="item.kind==='episode'">{{ $t('items.episodeNumber',{season:item.season_number ?? '?',episode:item.episode_number ?? '?'}) }}</template><template v-else>{{ item.year || $t(`items.kind.${item.kind}`) }}</template></p>
      <time v-if="item.kind==='episode' && item.release_date" :datetime="item.release_date" class="mt-1 block pr-10 text-xs text-muted">{{ formatReleaseDate(item.release_date,locale) }}</time>
    </RouterLink>
    <div class="absolute bottom-0 right-0"><WatchStateMenu :item-id="item.id" :kind="item.kind" :watched="item.watched" :state-revision="item.state_revision" @changed="emit('changed')" /></div>
  </article>
</template>
