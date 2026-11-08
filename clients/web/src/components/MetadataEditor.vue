<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type MetadataItem, type MetadataJob, metadata } from "@/api/client";
import EpisodeAssociationForm from "@/components/EpisodeAssociationForm.vue";
import ModalDialog from "@/components/ModalDialog.vue";

const props=defineProps<{itemId:number}>();
const emit=defineEmits<{close:[];saved:[];associated:[itemId:number]}>();
const {t,te}=useI18n();
const value=ref<MetadataItem|null>(null);
const pending=ref(false);
const loading=ref(true);
const error=ref("");
const notice=ref("");
const reloadRequired=ref(false);
const draft=ref<Record<string,string>>({});
const locks=ref<string[]>([]);
const locked=ref(false);
const restoreFields=ref<string[]>([]);
const searchQuery=ref("");
const matches=ref<Awaited<ReturnType<typeof metadata.search>>>([]);
const searchLoading=ref(false);
const searched=ref(false);
const provider=ref<"tmdb"|"anidb">("tmdb");
const providerError=ref("");
const providerStatus=ref<Awaited<ReturnType<typeof metadata.providers>>|null>(null);
const lifetime=new AbortController();
let searchRequest:AbortController|undefined;
const textFields=["title","original_title","sort_title","tagline","overview","original_language","release_date","season_number","episode_number"] as const;
const structuredFields=["aliases","genres","keywords","credits","studios","countries","provider_ids"] as const;
const allFields=[...textFields,...structuredFields];
const visibleTextFields=computed(()=>textFields.filter(field=>{
  if((field==="season_number" || field==="episode_number") && value.value?.can_associate_episode)return false;
  return field === "season_number" ? ["season","episode"].includes(value.value?.kind || "") : field === "episode_number" ? value.value?.kind === "episode" : true;
}));
const canIdentify=computed(()=>value.value?.kind === "movie" || value.value?.kind === "series");
const hasProvider=computed(()=>providerStatus.value?.tmdb_configured || providerStatus.value?.anidb_configured);
function snapshot(item:MetadataItem){
  return Object.fromEntries(allFields.map(field=>[field,structuredFields.includes(field as typeof structuredFields[number]) ? JSON.stringify(item[field],null,2) : String(item[field] ?? "")]));
}
const dirty=computed(()=>value.value && (JSON.stringify(draft.value)!==JSON.stringify(snapshot(value.value)) || locked.value!==value.value.locked || [...locks.value].sort().join()!==[...value.value.locked_fields].sort().join()));
function adopt(item:MetadataItem){value.value=item;draft.value=snapshot(item);locks.value=[...item.locked_fields];locked.value=item.locked;restoreFields.value=[];}
function errorMessage(cause:unknown){return cause && typeof cause==="object" && "status" in cause && cause.status===409 ? t("metadata.conflict") : cause instanceof Error ? cause.message : t("metadata.failed");}
async function load():Promise<boolean>{
  loading.value=true;error.value="";notice.value="";
  try{
    const result=await metadata.get(props.itemId,lifetime.signal);lifetime.signal.throwIfAborted();
    adopt(result);searchQuery.value=result.title;reloadRequired.value=false;return true;
  }catch(cause){
    if(!lifetime.signal.aborted){error.value=errorMessage(cause);reloadRequired.value=!!value.value;}
    return false;
  }finally{if(!lifetime.signal.aborted)loading.value=false;}
}
async function mutate(action:()=>Promise<MetadataItem|MetadataJob>,message="metadata.saved"){
  if(pending.value || reloadRequired.value) return;
  pending.value=true;error.value="";notice.value="";
  try{
    const result=await action();if(lifetime.signal.aborted)return;
    // Synchronous edits return the authoritative new revision: no extra GET race.
    if(result && "locked_fields" in result)adopt(result);
    else if(!await load()){emit("saved");return;}
    notice.value=t(message);emit("saved");
  }catch(cause){
    if(!lifetime.signal.aborted){
      error.value=errorMessage(cause);
      if(cause && typeof cause==="object" && "status" in cause && cause.status===409)reloadRequired.value=true;
    }
  }finally{pending.value=false;}
}
async function save(){
  if(!value.value)return;
  const changes:Record<string,unknown>={};
  const original=snapshot(value.value);
  try{
    for(const field of allFields){
      if(draft.value[field]===original[field])continue;
      if(structuredFields.includes(field as typeof structuredFields[number])) changes[field]=JSON.parse(draft.value[field]);
      else if(field==="season_number" || field==="episode_number") changes[field]=draft.value[field] ? Number(draft.value[field]) : null;
      else changes[field]=field==="title" ? draft.value[field].trim() : draft.value[field] || null;
    }
  }catch{error.value=t("metadata.invalidJson");return;}
  const payload={expected_revision:value.value.revision,changes,locked_fields:locks.value,locked:locked.value};
  await mutate(()=>metadata.update(props.itemId,payload));
}
async function search(){
  if(!value.value || !canIdentify.value || !searchQuery.value.trim())return;
  searchRequest?.abort();const controller=new AbortController();searchRequest=controller;
  searchLoading.value=true;searched.value=false;error.value="";matches.value=[];
  try{const result=await metadata.search(searchQuery.value.trim(),value.value.kind === "movie" ? "movie" : "series",value.value.metadata_locale,provider.value,controller.signal);controller.signal.throwIfAborted();matches.value=result;searched.value=true;}
  catch(cause){if(!controller.signal.aborted)error.value=errorMessage(cause);}
  finally{if(!controller.signal.aborted)searchLoading.value=false;}
}
async function identify(candidate:Awaited<ReturnType<typeof metadata.search>>[number]){
  if(!value.value)return;
  const revision=value.value.revision;
  await mutate(()=>metadata.identify(props.itemId,revision,candidate.provider as "tmdb"|"anidb",candidate.provider_id),"metadata.queued");
}
async function refresh(mode:"missing"|"unlocked"){
  if(!value.value)return;
  const revision=value.value.revision;
  await mutate(()=>metadata.refresh(props.itemId,revision,mode),"metadata.queued");
}
async function restore(){
  if(!value.value || !restoreFields.value.length)return;
  const revision=value.value.revision;const fields=[...restoreFields.value];
  await mutate(()=>metadata.restore(props.itemId,revision,fields));
}
async function upload(event:Event,role:"poster"|"backdrop"){
  const input=event.target as HTMLInputElement;const file=input.files?.[0];
  if(!value.value || !file)return;
  const revision=value.value.revision;
  await mutate(()=>metadata.uploadImage(props.itemId,role,file,revision));input.value="";
}
async function loadProviders(){
  providerError.value="";
  try{const result=await metadata.providers(lifetime.signal);lifetime.signal.throwIfAborted();providerStatus.value=result;if(!result.tmdb_configured && result.anidb_configured)provider.value="anidb";}
  catch{if(!lifetime.signal.aborted)providerError.value=t("metadata.providersFailed");}
}
onMounted(()=>{void load();void loadProviders();});
onUnmounted(()=>{lifetime.abort();searchRequest?.abort();});
</script>

<template>
  <ModalDialog :label="$t('metadata.edit')" @close="!pending && emit('close')">
    <section class="surface-panel max-h-[88dvh] w-full max-w-4xl overflow-y-auto p-5 sm:p-8">
      <header class="mb-6 flex items-start justify-between gap-5"><div><h2 class="text-xl font-semibold">{{ $t('metadata.edit') }}</h2><p v-if="value" class="mt-2 text-xs text-muted">{{ $t('metadata.status') }} : {{ te(`metadata.itemStatus.${value.metadata_status}`) ? $t(`metadata.itemStatus.${value.metadata_status}`) : value.metadata_status }} · {{ value.metadata_locale }}</p></div><button type="button" :disabled="pending" class="button-secondary" @click="emit('close')">{{ $t('common.close') }}</button></header>
      <div v-if="error" role="alert" class="form-error mb-5"><p>{{ error }}</p><button v-if="reloadRequired" type="button" :disabled="pending || loading" class="mt-3 underline" @click="load">{{ $t('metadata.reload') }}</button></div><p v-if="notice" role="status" class="mb-5 text-sm text-emerald-300">{{ notice }}</p>
      <p v-if="loading" role="status">{{ $t('common.loading') }}</p>
      <button v-else-if="!value" type="button" class="button-secondary" @click="load">{{ $t('common.retry') }}</button>
      <template v-else>
        <fieldset v-if="value.can_associate_episode" :disabled="pending || reloadRequired || !!dirty" class="mb-8 border-b border-outline pb-7"><EpisodeAssociationForm v-if="value.can_associate_episode" :key="value.revision" :item="value" @conflict="reloadRequired=true;error=t('metadata.conflict')" @busy="pending=$event" @associated="emit('associated',$event)" /></fieldset>
        <form @submit.prevent="save">
          <fieldset :disabled="pending || reloadRequired" class="space-y-5">
            <label class="flex items-center gap-3 text-sm"><input v-model="locked" type="checkbox" class="size-4 accent-primary-500" />{{ $t('metadata.lockAll') }}</label>
            <p class="text-xs leading-5 text-muted">{{ $t('metadata.lockHelp') }}</p>
            <div class="flex flex-wrap gap-5"><label v-for="field in ['poster','backdrop','order']" :key="field" class="flex items-center gap-2 text-xs text-muted"><input v-model="locks" :value="field" type="checkbox" class="accent-primary-500" />{{ $t('metadata.lock') }} · {{ $t(`metadata.${field}`) }}</label></div>
            <div class="grid gap-5 sm:grid-cols-2">
              <div v-for="field in visibleTextFields" :key="field" :class="field==='overview' ? 'sm:col-span-2' : ''" class="space-y-2">
                <div class="flex items-center justify-between gap-3"><label :for="`metadata-${field}`" class="field-label">{{ $t(`metadata.fields.${field}`) }}</label><label class="flex items-center gap-2 text-xs text-muted"><input v-model="locks" :value="field" type="checkbox" class="accent-primary-500" />{{ $t('metadata.lock') }}</label></div>
                <textarea v-if="field==='overview'" :id="`metadata-${field}`" v-model="draft[field]" rows="4" class="field-input"></textarea>
                <input v-else :id="`metadata-${field}`" v-model="draft[field]" :type="field==='release_date' ? 'date' : field.endsWith('_number') ? 'number' : 'text'" :min="field.endsWith('_number') ? 0 : undefined" :required="field==='title'" class="field-input" />
              </div>
            </div>
            <details class="rounded-sm border border-outline p-4"><summary class="cursor-pointer text-sm font-medium">{{ $t('metadata.advanced') }}</summary><p class="mt-3 text-xs leading-5 text-muted">{{ $t('metadata.advancedHelp') }}</p><div class="mt-5 space-y-5"><div v-for="field in structuredFields" :key="field" class="space-y-2"><div class="flex justify-between gap-4"><label :for="`metadata-${field}`" class="field-label">{{ $t(`metadata.fields.${field}`) }}</label><label class="flex items-center gap-2 text-xs text-muted"><input v-model="locks" :value="field" type="checkbox" class="accent-primary-500" />{{ $t('metadata.lock') }}</label></div><textarea :id="`metadata-${field}`" v-model="draft[field]" rows="5" class="field-input font-mono text-sm" :spellcheck="false"></textarea></div></div></details>
            <button type="submit" :disabled="pending || reloadRequired || !dirty" class="button-primary">{{ $t('common.save') }}</button>
          </fieldset>
        </form>
        <p v-if="dirty" class="my-6 text-xs text-muted">{{ $t('metadata.saveBeforeActions') }}</p>
        <fieldset :disabled="pending || reloadRequired || !!dirty" class="mt-8 space-y-7 border-t border-outline pt-7">
          <p v-if="providerError" role="alert" class="form-error">{{ providerError }} <button type="button" class="underline" @click="loadProviders">{{ $t('common.retry') }}</button></p>
          <section v-if="canIdentify" class="space-y-4"><h3 class="font-semibold">{{ $t('metadata.identify') }}</h3><p v-if="providerStatus && !hasProvider" class="text-sm text-muted">{{ $t('metadata.providerUnavailable') }}</p><label v-if="providerStatus?.tmdb_configured && providerStatus?.anidb_configured" class="block space-y-2"><span class="field-label">{{ $t('metadata.provider') }}</span><select v-model="provider" class="field-input"><option value="tmdb">TMDB</option><option value="anidb">AniDB</option></select></label><form class="flex flex-wrap gap-3" @submit.prevent="search"><label for="metadata-query" class="sr-only">{{ $t('discovery.title') }}</label><input id="metadata-query" v-model="searchQuery" type="search" class="field-input min-w-0 flex-1" required maxlength="200" /><button type="submit" :disabled="searchLoading || !hasProvider" class="button-secondary">{{ $t('discovery.action') }}</button></form><p v-if="searchLoading" role="status">{{ $t('common.loading') }}</p><p v-if="searched && !matches.length" role="status" class="text-sm text-muted">{{ $t('metadata.noMatches') }}</p><ul class="space-y-3"><li v-for="candidate in matches" :key="`${candidate.provider}:${candidate.provider_id}`" class="rounded-sm border border-outline p-4"><div class="flex items-start justify-between gap-4"><div><p class="font-medium">{{ candidate.title }} <span class="text-muted">{{ candidate.year }}</span></p><p class="mt-1 text-xs text-muted">{{ candidate.provider }} · {{ candidate.provider_id }}</p></div><button type="button" class="button-secondary" @click="identify(candidate)">{{ $t('metadata.identifyAction') }}</button></div><p v-if="candidate.overview" class="mt-3 text-sm leading-6 text-muted">{{ candidate.overview }}</p></li></ul></section>
          <section class="space-y-4"><h3 class="font-semibold">{{ $t('metadata.refresh') }}</h3><div class="flex flex-wrap gap-3"><button type="button" :disabled="locked" class="button-secondary" @click="refresh('missing')">{{ $t('metadata.refreshMissing') }}</button><button type="button" :disabled="locked" class="button-secondary" @click="refresh('unlocked')">{{ $t('metadata.refreshUnlocked') }}</button><RouterLink to="/dashboard/jobs" class="inline-flex items-center text-sm text-primary-300">{{ $t('metadata.viewJobs') }} →</RouterLink></div></section>
          <section class="space-y-4"><h3 class="font-semibold">{{ $t('metadata.restore') }}</h3><p class="text-xs leading-5 text-muted">{{ $t('metadata.restoreHelp') }}</p><div class="grid gap-3 sm:grid-cols-3"><label v-for="field in allFields" :key="field" class="flex items-center gap-2 text-sm"><input v-model="restoreFields" :value="field" type="checkbox" class="accent-primary-500" />{{ $t(`metadata.fields.${field}`) }}</label></div><button type="button" :disabled="!restoreFields.length" class="button-secondary" @click="restore">{{ $t('metadata.restoreAction') }}</button></section>
          <section class="space-y-4"><h3 class="font-semibold">{{ $t('metadata.images') }}</h3><div class="grid gap-4 sm:grid-cols-2"><div v-for="role in (['poster','backdrop'] as const)" :key="role" class="space-y-2"><label :for="`metadata-image-${role}`" class="field-label">{{ $t(`metadata.${role}`) }}</label><input :id="`metadata-image-${role}`" type="file" accept="image/jpeg,image/png,image/webp" class="max-w-full text-sm text-muted file:mr-3 file:rounded-sm file:border-0 file:bg-surface-raised file:px-3 file:py-2 file:text-white" @change="upload($event,role)" /></div></div></section>
        </fieldset>
      </template>
    </section>
  </ModalDialog>
</template>
