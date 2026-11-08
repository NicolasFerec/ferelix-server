<script setup lang="ts">
import { computed, defineAsyncComponent, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { type ItemCard, type ItemDetail, items } from "@/api/client";
import ItemCardView from "@/components/ItemCard.vue";
import MenuBar from "@/components/MenuBar.vue";
import WatchlistButton from "@/components/WatchlistButton.vue";
import WatchStateMenu from "@/components/WatchStateMenu.vue";
import { useUser } from "@/composables/useUser";
import { safeReturnTo } from "@/services/authNavigation";
import { formatReleaseDate } from "@/services/mediaDisplay";

const MetadataEditor=defineAsyncComponent(()=>import("@/components/MetadataEditor.vue"));
const {t,locale}=useI18n();
const route=useRoute();
const router=useRouter();
const {isAdmin}=useUser();
const item=ref<ItemDetail|null>(null);
const loading=ref(true);
const error=ref("");
const revision=ref(0);
const editing=ref(false);
const seasons=ref<ItemCard[]>([]);
const seasonsMore=ref(false);
const seasonsLoading=ref(false);
const seasonsError=ref("");
const selectedSeason=ref<number|null>(null);
const deepSeason=ref<ItemCard|null>(null);
const displaySeasons=computed(()=>deepSeason.value && !seasons.value.some(season=>season.id===deepSeason.value?.id) ? [...seasons.value,deepSeason.value] : seasons.value);
let seasonSelectionRevision=0;
const children=ref<ItemCard[]>([]);
const childrenLoading=ref(false);
const childrenError=ref("");
const hasNext=ref(false);
const continuation=ref<Awaited<ReturnType<typeof items.continuation>>|null>(null);
const continuationError=ref("");
let itemRequest:AbortController|undefined;
let childrenRequest:AbortController|undefined;
const page=computed(()=>Math.max(1,Math.min(1000000,Math.floor(Number(route.query.page)||1))));
const backLocation=computed(()=>route.query.returnTo ? safeReturnTo(route.query.returnTo) : item.value?.parent_id ? `/items/${item.value.parent_id}` : "/");
const poster=computed(()=>items.artworkUrl(item.value?.poster_url));
const backdrop=computed(()=>items.artworkUrl(item.value?.backdrop_url));
const playable=computed(()=>item.value?.kind === "series" || item.value?.kind === "season" ? continuation.value?.status === "ready" ? continuation.value.item : null : item.value?.availability === "available" && item.value.playable_file_id ? item.value : null);
const playLocation=computed(()=>({name:"player",params:{id:String(playable.value?.playable_file_id)},query:{item:String(playable.value?.id),position:String(continuation.value?.status === "ready" ? continuation.value.position_seconds : playable.value?.position_seconds ?? 0),returnTo:route.fullPath}}));
const childrenParent=computed(()=>item.value?.kind === "series" ? selectedSeason.value : item.value?.kind === "season" ? item.value.id : null);
const hasChildren=computed(()=>item.value && ["series","season","collection"].includes(item.value.kind));
function label(value:Record<string,unknown>){return typeof value.name==="string" ? value.name : "";}
async function selectSeasonFromQuery(signal:AbortSignal){
  const selection=++seasonSelectionRevision;
  const parent=item.value?.id;
  const requested=Number(route.query.season);
  let chosen=seasons.value.find(season=>season.id===requested);
  if(!chosen && Number.isInteger(requested) && requested>0){
    const result=await items.get(requested,signal).catch(()=>null);
    signal.throwIfAborted();
    if(result?.kind==="season" && result.parent_id===parent)chosen=result;
  }
  if(signal.aborted || selection!==seasonSelectionRevision)return;
  deepSeason.value=chosen && !seasons.value.some(season=>season.id===chosen?.id) ? chosen : null;
  selectedSeason.value=chosen?.id ?? seasons.value.find(season=>(season.season_number||0)>0)?.id ?? seasons.value[0]?.id ?? null;
}
async function openAssociatedItem(itemId:number){
  editing.value=false;
  await router.replace({name:"item-detail",params:{id:itemId},query:route.query.returnTo ? {returnTo:route.query.returnTo} : {}});
}
async function loadSeasons(append=false){
  const current = item.value;
  const controller = itemRequest;
  if(!current || !controller || (append && seasonsLoading.value)) return;
  seasonsLoading.value=true;seasonsError.value="";
  try{
    const rows=await items.list({parent_id:current.id,kind:"season",skip:append ? seasons.value.length : 0,limit:51},controller.signal);
    controller.signal.throwIfAborted();
    seasonsMore.value=rows.length>50;
    seasons.value=append ? [...seasons.value,...rows.slice(0,50)] : rows.slice(0,50);
    if(!append) await selectSeasonFromQuery(controller.signal);
  }catch(cause){if(!controller.signal.aborted) seasonsError.value=cause instanceof Error ? cause.message : t("items.loadFailed");}
  finally{if(itemRequest===controller)seasonsLoading.value=false;}
}
watch([()=>route.params.id,revision],async(_,__ ,onCleanup)=>{
  const controller=new AbortController();itemRequest=controller;onCleanup(()=>controller.abort());
  const changedItem=item.value?.id!==Number(route.params.id);
  loading.value=changedItem;error.value="";continuation.value=null;continuationError.value="";
  if(changedItem){editing.value=false;selectedSeason.value=null;deepSeason.value=null;seasons.value=[];seasonsMore.value=false;}
  try{
    const result=await items.get(Number(route.params.id),controller.signal);controller.signal.throwIfAborted();item.value=result;
    if(result.kind==="series") await loadSeasons();
    if(result.kind==="series" || result.kind==="season") {
      try{const next=await items.continuation(result.id,"continue",controller.signal);controller.signal.throwIfAborted();continuation.value=next;}
      catch{if(!controller.signal.aborted) continuationError.value=t("items.continuationFailed");}
    }
  }catch{if(!controller.signal.aborted)error.value=t("items.loadFailed");}
  finally{if(!controller.signal.aborted)loading.value=false;}
},{immediate:true});
watch([()=>item.value?.id,childrenParent,page,revision],async(_,__,onCleanup)=>{
  const controller=new AbortController();childrenRequest=controller;onCleanup(()=>controller.abort());
  childrenError.value="";
  if(!hasChildren.value || (item.value?.kind!=="collection" && !childrenParent.value)){children.value=[];childrenLoading.value=false;hasNext.value=false;return;}
  childrenLoading.value=true;
  try{
    const result=await items.list({...(item.value?.kind==="collection" ? {collection_id:item.value.id} : {parent_id:childrenParent.value ?? undefined,kind:"episode" as const}),skip:(page.value-1)*48,limit:49},controller.signal);
    controller.signal.throwIfAborted();hasNext.value=result.length>48;children.value=result.slice(0,48);
  }catch{if(!controller.signal.aborted)childrenError.value=t("items.loadFailed");}
  finally{if(!controller.signal.aborted)childrenLoading.value=false;}
},{immediate:true});
watch(()=>route.query.season,async(_,__,onCleanup)=>{
  if(item.value?.kind!=="series")return;
  const controller=new AbortController();onCleanup(()=>controller.abort());
  try{await selectSeasonFromQuery(itemRequest ? AbortSignal.any([controller.signal,itemRequest.signal]) : controller.signal);}catch{ /* obsolete selection */ }
});
onUnmounted(()=>{itemRequest?.abort();childrenRequest?.abort();});
</script>

<template>
  <div class="min-h-screen bg-background">
    <MenuBar />
    <main id="main-content">
      <p v-if="loading" role="status" class="page-shell empty-state">{{ $t('common.loading') }}</p>
      <div v-else-if="error" role="alert" class="page-shell empty-state"><p class="mb-4 text-red-200">{{ error }}</p><button type="button" class="button-secondary" @click="revision++">{{ $t('common.retry') }}</button></div>
      <template v-else-if="item">
        <div class="relative overflow-hidden">
          <img v-if="backdrop" :src="backdrop" alt="" class="pointer-events-none absolute inset-0 size-full object-cover opacity-20" />
          <div class="pointer-events-none absolute inset-0 bg-linear-to-t from-background via-background/60 to-transparent"></div>
          <div class="page-shell relative">
            <RouterLink :to="backLocation" class="mb-7 inline-flex items-center gap-2 text-sm text-muted hover:text-white">← {{ $t('common.back') }}</RouterLink>
            <div class="flex flex-col gap-8 md:flex-row">
              <div class="w-40 shrink-0 sm:w-48 md:w-56"><div class="aspect-2/3 overflow-hidden rounded-sm bg-surface"><img v-if="poster" :src="poster" :alt="item.title" width="480" height="720" class="size-full object-cover" /><div v-else class="flex size-full items-center justify-center p-5 text-center text-muted">{{ item.title }}</div></div></div>
              <div class="min-w-0 flex-1 space-y-5">
                <p class="text-xs uppercase tracking-widest text-muted">{{ $t(`items.kind.${item.kind}`) }}<span v-if="item.kind==='episode'"> · {{ $t('items.episodeNumber',{season:item.season_number ?? '?',episode:item.episode_number ?? '?'}) }}</span></p>
                <h1 class="page-heading">{{ item.title }}</h1>
                <p v-if="item.original_title && item.original_title!==item.title" class="text-sm text-muted">{{ item.original_title }}</p>
                <div class="flex flex-wrap gap-3 text-sm text-muted"><time v-if="item.kind==='episode' && item.release_date" :datetime="item.release_date">{{ formatReleaseDate(item.release_date,locale) }}</time><span v-else-if="item.year">{{ item.year }}</span><span v-for="genre in item.genres" :key="label(genre)">{{ label(genre) }}</span><span v-if="item.watched">{{ $t('mediaDetail.watched') }}</span></div>
                <p v-if="item.tagline" class="text-base italic text-gray-300">{{ item.tagline }}</p>
                <p v-if="item.overview" class="max-w-3xl whitespace-pre-line text-sm leading-7 text-gray-300">{{ item.overview }}</p>
                <div class="flex flex-wrap items-start gap-3">
                  <RouterLink v-if="playable" :to="playLocation" class="button-primary"><svg aria-hidden="true" class="size-5" viewBox="0 0 24 24" fill="currentColor"><path d="M9 5v14l11-7z"/></svg>{{ $t(playable.resume_active ? 'mediaDetail.resume' : item.kind==='series' || item.kind==='season' ? 'items.continue' : 'mediaDetail.play') }}</RouterLink>
                  <WatchlistButton v-if="item.playable_file_id" :media-id="item.playable_file_id" :in-watchlist="item.in_watchlist" @updated="item.in_watchlist=$event" />
                  <WatchStateMenu direct :item-id="item.id" :kind="item.kind" :watched="item.watched" :state-revision="item.state_revision" @changed="revision++" />
                  <button v-if="isAdmin" type="button" class="button-secondary" @click="editing=true">{{ $t('metadata.edit') }}</button>
                </div>
                <p v-if="continuationError" role="alert" class="text-sm text-red-200">{{ continuationError }}</p>
                <p v-else-if="continuation && continuation.status!=='ready'" class="text-sm text-muted">{{ $t(`items.continuation.${continuation.status}`) }}<span v-if="continuation.item"> · {{ continuation.item.title }}</span></p>
                <p v-else-if="item.availability!=='available' && !playable" class="text-sm text-muted">{{ $t(`items.availability.${item.availability}`) }}</p>
                <p v-if="item.multi_episode_file" class="max-w-2xl text-xs leading-5 text-muted">{{ $t('items.multiEpisode') }}</p>
                <div class="flex flex-wrap gap-5 text-sm text-primary-300"><RouterLink v-if="item.series_id && item.series_id!==item.id" :to="`/items/${item.series_id}`">{{ $t('items.viewSeries') }}</RouterLink><RouterLink v-if="item.collection_id" :to="`/items/${item.collection_id}`">{{ $t('items.viewCollection') }}</RouterLink></div>
              </div>
            </div>
          </div>
        </div>
        <section v-if="hasChildren" class="page-shell pt-0">
          <h2 class="mb-5 text-xl font-semibold">{{ $t(item.kind==='collection' ? 'items.collectionTitles' : 'items.episodes') }}</h2>
          <nav v-if="item.kind==='series'" class="mb-6 flex flex-wrap items-center gap-2" :aria-label="$t('items.seasons')">
            <RouterLink v-for="season in displaySeasons" :key="season.id" :to="{query:{...route.query,season:String(season.id),page:undefined}}" class="rounded-sm px-4 py-2 text-sm" :class="selectedSeason===season.id ? 'bg-white/10 text-white' : 'text-muted hover:text-white'" :aria-current="selectedSeason===season.id ? 'page' : undefined">{{ season.title || $t('items.seasonNumber',{number:season.season_number}) }}</RouterLink>
            <button v-if="seasonsMore" type="button" :disabled="seasonsLoading" class="button-secondary" @click="loadSeasons(true)">{{ $t('items.moreSeasons') }}</button>
          </nav>
          <p v-if="seasonsError || childrenError" role="alert" class="form-error">{{ seasonsError || childrenError }}<button type="button" class="ml-3 underline" @click="revision++">{{ $t('common.retry') }}</button></p>
          <p v-else-if="childrenLoading" role="status" class="empty-state">{{ $t('common.loading') }}</p>
          <div v-else-if="children.length" class="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6"><ItemCardView v-for="child in children" :key="child.id" :item="child" :return-to="route.fullPath" @changed="revision++" /></div>
          <p v-else class="empty-state">{{ $t(item.hierarchy_complete ? 'items.noChildren' : 'items.hierarchyPending') }}</p>
          <nav v-if="page>1 || hasNext" class="mt-8 flex justify-between gap-4" :aria-label="$t('library.pagination')"><RouterLink v-if="page>1" :to="{query:{...route.query,page:String(page-1)}}" class="button-secondary">← {{ $t('common.previous') }}</RouterLink><span v-else></span><RouterLink v-if="hasNext" :to="{query:{...route.query,page:String(page+1)}}" class="button-secondary">{{ $t('common.next') }} →</RouterLink></nav>
        </section>
        <section v-if="item.credits.length" class="page-shell pt-0"><h2 class="mb-5 text-xl font-semibold">{{ $t('metadata.credits') }}</h2><ul class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><li v-for="(credit,index) in item.credits.slice(0,24)" :key="index" class="text-sm"><span>{{ label(credit) }}</span><p v-if="typeof credit.character==='string'" class="mt-1 text-xs text-muted">{{ credit.character }}</p></li></ul></section>

      </template>
    </main>
    <MetadataEditor v-if="editing && isAdmin && item" :key="item.id" :item-id="item.id" @close="editing=false" @saved="revision++" @associated="openAssociatedItem" />
  </div>
</template>
