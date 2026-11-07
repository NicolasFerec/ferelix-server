<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type ItemCard, items } from "@/api/client";
import ModalDialog from "@/components/ModalDialog.vue";

const props=defineProps<{itemId:number;kind:ItemCard["kind"];watched:boolean;stateRevision:number}>();
const emit=defineEmits<{changed:[]}>();
const {t}=useI18n();
const trigger=ref<HTMLButtonElement|null>(null);
const menu=ref<HTMLElement|null>(null);
const menuOpen=ref(false);
const menuId=useId();
const menuPosition=ref({left:"0px",top:"0px"});
const currentWatched=ref(props.watched);
const revision=ref(props.stateRevision);
const pending=ref(false);
const error=ref("");
const bulk=computed(()=>["series","season","collection"].includes(props.kind));
const dialog=ref(false);
const targetWatched=ref(true);
const preview=ref<{count:number;revision_token:string}|null>(null);
watch(()=>[props.itemId,props.watched,props.stateRevision],()=>{currentWatched.value=props.watched;revision.value=props.stateRevision;error.value="";});
async function toggleMenu() {
  const rect=trigger.value?.getBoundingClientRect();
  if(!rect)return;
  menuPosition.value={left:`${Math.max(8,Math.min(window.innerWidth-248,rect.right-240))}px`,top:`${Math.max(8,Math.min(window.innerHeight-90,rect.bottom+8))}px`};
  menuOpen.value=!menuOpen.value;
  if(menuOpen.value){await nextTick();menu.value?.querySelector("button")?.focus({preventScroll:true});}
}
function closeMenu(event:Event){
  if(event.type==="pointerdown" && event.target instanceof Node && (trigger.value?.contains(event.target) || menu.value?.contains(event.target)))return;
  menuOpen.value=false;
}
function handleKey(event:KeyboardEvent){if(event.key==="Escape" && menuOpen.value){event.stopPropagation();menuOpen.value=false;trigger.value?.focus();}}
watch(menuOpen,(open,_,onCleanup)=>{
  if(!open)return;
  document.addEventListener("pointerdown",closeMenu);window.addEventListener("resize",closeMenu);window.addEventListener("scroll",closeMenu,true);
  onCleanup(()=>{document.removeEventListener("pointerdown",closeMenu);window.removeEventListener("resize",closeMenu);window.removeEventListener("scroll",closeMenu,true);});
});
function failure(cause:unknown) {
  return cause && typeof cause==="object" && "status" in cause && cause.status===409 ? t("items.stateConflict") : t("items.stateFailed");
}
async function previewBulk(watched:boolean) {
  if(pending.value) return;
  targetWatched.value=watched;dialog.value=true;preview.value=null;pending.value=true;error.value="";
  menuOpen.value=false;trigger.value?.focus({preventScroll:true});
  try { const result=await items.bulkWatched(props.itemId,watched);preview.value={count:result.count,revision_token:result.revision_token}; }
  catch(cause){error.value=failure(cause);}
  finally{pending.value=false;}
}
async function setWatched(watched:boolean) {
  if(bulk.value) {await previewBulk(watched);return;}
  if(pending.value) return;
  pending.value=true;error.value="";
  menuOpen.value=false;trigger.value?.focus({preventScroll:true});
  try{const state=await items.setWatched(props.itemId,watched,revision.value);currentWatched.value=state.watched;revision.value=state.state_revision;emit("changed");}
  catch(cause){
    error.value=failure(cause);
    if(cause && typeof cause==="object" && "status" in cause && cause.status===409){
      const item=await items.get(props.itemId).catch(()=>null);
      if(item){currentWatched.value=item.watched;revision.value=item.state_revision;}
    }
  } finally{pending.value=false;}
}
async function confirmBulk() {
  if(pending.value || !preview.value) return;
  pending.value=true;error.value="";
  try{await items.bulkWatched(props.itemId,targetWatched.value,preview.value.revision_token);currentWatched.value=targetWatched.value;dialog.value=false;emit("changed");}
  catch(cause){error.value=failure(cause);preview.value=null;}
  finally{pending.value=false;}
}
</script>

<template>
  <div class="relative">
    <button ref="trigger" type="button" class="watch-state-trigger flex size-9 items-center justify-center rounded-sm bg-black/65 text-white" :aria-label="$t('items.watchActions')" :aria-controls="menuId" :aria-expanded="menuOpen" :aria-busy="pending" :title="$t(currentWatched ? 'items.markUnwatched' : 'items.markWatched')" @click="toggleMenu" @keydown="handleKey"><svg aria-hidden="true" class="size-5" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg></button>
    <Teleport to="body">
      <div v-if="menuOpen" :id="menuId" ref="menu" class="fixed z-[70] w-60 rounded-sm border border-outline bg-surface p-1 text-foreground shadow-xl" :style="menuPosition">
        <button type="button" :disabled="pending" @keydown="handleKey" class="watch-state-action block w-full px-3 py-3 text-left text-sm hover:bg-white/5 disabled:opacity-50" @click="setWatched(!currentWatched)">{{ $t(currentWatched ? 'items.markUnwatched' : 'items.markWatched') }}</button>
      </div>
    </Teleport>
    <Teleport to="body"><div v-if="error && !dialog" role="alert" :style="menuPosition" class="fixed z-[70] w-60 rounded-sm bg-surface p-3 text-xs leading-relaxed text-red-200"><p>{{ error }}</p><button type="button" class="mt-3 underline" @click="error=''">{{ $t('common.close') }}</button></div></Teleport>
    <ModalDialog v-if="dialog" :label="$t('items.bulkTitle')" @close="!pending && (dialog=false)">
      <section class="surface-panel w-full max-w-md space-y-5 p-6">
        <h2 class="text-xl font-semibold">{{ $t('items.bulkTitle') }}</h2>
        <p v-if="pending" role="status" class="text-sm text-muted">{{ $t('common.loading') }}</p>
        <p v-if="preview" class="text-sm leading-6">{{ $t(targetWatched ? 'items.bulkWatched' : 'items.bulkUnwatched',{count:preview.count}) }}</p>
        <p v-if="error" role="alert" class="form-error">{{ error }}</p>
        <div class="flex flex-wrap justify-end gap-3">
          <button type="button" :disabled="pending" class="button-secondary" @click="dialog=false">{{ $t('common.cancel') }}</button>
          <button v-if="!preview && !pending" type="button" class="button-secondary" @click="previewBulk(targetWatched)">{{ $t('common.retry') }}</button>
          <button v-if="preview" type="button" :disabled="pending || preview.count===0" class="button-primary" @click="confirmBulk">{{ $t('items.confirm') }}</button>
        </div>
      </section>
    </ModalDialog>
  </div>
</template>
