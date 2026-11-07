<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { type Library, type LibraryCreate, libraries as libraryApi } from "@/api/client";
import DirectoryBrowser from "./DirectoryBrowser.vue";
import ModalDialog from "./ModalDialog.vue";

const props=defineProps<{library?:Library|null}>();
const emit=defineEmits<{close:[];saved:[]}>();
const {t}=useI18n();
const defaults=():LibraryCreate=>({name:"",path:"",library_type:"movie",enabled:true,metadata_locale:"fr-FR",metadata_profile:"standard",metadata_export_nfo:false});
const form=ref<LibraryCreate>(defaults());
const loading=ref(false);
const error=ref("");
const showBrowser=ref(false);
watch(()=>props.library,library=>{
  form.value=library ? {name:library.name,path:library.path,library_type:library.library_type,enabled:library.enabled,metadata_locale:library.metadata_locale,metadata_profile:library.metadata_profile,metadata_export_nfo:library.metadata_export_nfo} : defaults();
  error.value="";
},{immediate:true});
async function handleSubmit(){
  if(loading.value) return;
  if(!form.value.name.trim()){error.value=t("libraries.nameRequired");return;}
  if(!form.value.path.trim()){error.value=t("libraries.pathRequired");return;}
  loading.value=true;error.value="";
  try{
    const payload={...form.value,name:form.value.name.trim(),path:form.value.path.trim()};
    if(props.library?.id) await libraryApi.updateLibrary(props.library.id,payload);
    else await libraryApi.createLibrary(payload);
    emit("saved");
  }catch{error.value=t(props.library ? "libraries.updateFailed" : "libraries.createFailed");}
  finally{loading.value=false;}
}
function handlePathSelect(path:string){form.value.path=path;showBrowser.value=false;}
</script>

<template>
  <ModalDialog :label="library ? $t('libraries.edit') : $t('libraries.add')" @close="$emit('close')">
    <div class="surface-panel p-5 sm:p-6 w-full max-w-md">
      <h3 class="text-xl font-semibold text-white mb-4">
        {{ library ? $t('libraries.edit') : $t('libraries.add') }}
      </h3>

      <form @submit.prevent="handleSubmit">
        <div class="space-y-4">
          <!-- Name -->
          <div>
            <label for="library-name" class="field-label mb-2">
              {{ $t('libraries.name') }}
            </label>
            <input
              id="library-name" v-model="form.name"
              type="text"
              required
              class="field-input"
              :placeholder="$t('libraries.namePlaceholder')"
            />
          </div>

          <!-- Path -->
          <div>
            <label for="library-path" class="field-label mb-2">
              {{ $t('libraries.path') }}
            </label>
            <div class="flex space-x-2">
              <input
                id="library-path" v-model="form.path"
                type="text"
                required
                class="field-input min-w-0 flex-1"
                :placeholder="$t('libraries.pathPlaceholder')"
              />
              <button
                type="button"
                @click="showBrowser = true"
                class="px-4 py-2 bg-surface-raised hover:bg-gray-600 text-white rounded-md transition-colors text-sm font-medium"
                :title="$t('libraries.browse')"
              >
                {{ $t('libraries.browse') }}
              </button>
            </div>
          </div>

          <!-- Library Type -->
          <div>
            <label for="library-type" class="field-label mb-2">
              {{ $t('libraries.typeLabel') }}
            </label>
            <select
              id="library-type" v-model="form.library_type"
              class="field-input"
            >
              <option value="movie">{{ $t('libraries.type.movie') }}</option>
              <option value="tv_show">{{ $t('libraries.type.tv_show') }}</option>
            </select>
          </div>

          <div class="space-y-2"><label for="metadata-locale" class="field-label">{{ $t('metadata.locale') }}</label><input id="metadata-locale" v-model="form.metadata_locale" class="field-input" required pattern="[a-z]{2,3}(-[A-Z]{2})?" placeholder="fr-FR" /><p class="text-xs text-muted">{{ $t('metadata.localeHelp') }}</p></div>
          <div class="space-y-2"><label for="metadata-profile" class="field-label">{{ $t('metadata.profile') }}</label><select id="metadata-profile" v-model="form.metadata_profile" class="field-input"><option value="standard">{{ $t('metadata.standard') }}</option><option value="anime">{{ $t('metadata.anime') }}</option></select></div>
          <label class="flex items-start gap-3 text-sm leading-5"><input v-model="form.metadata_export_nfo" type="checkbox" class="mt-1 size-4 accent-primary-500" /><span>{{ $t('metadata.exportNfo') }}</span></label>

          <!-- Enabled -->
          <div class="flex items-center">
            <input
              v-model="form.enabled"
              type="checkbox"
              id="enabled"
              class="w-4 h-4 text-primary-600 bg-surface-raised border-gray-600 rounded-sm focus:ring-primary-500"
            />
            <label for="enabled" class="ml-2 text-sm font-medium text-gray-300">
              {{ $t('libraries.enabled') }}
            </label>
          </div>
        </div>

        <!-- Error message -->
        <div v-if="error" role="alert" class="form-error mt-4">
          {{ error }}
        </div>

        <!-- Actions -->
        <div class="mt-6 flex justify-end space-x-3">
          <button
            type="button"
            @click="$emit('close')"
            class="px-4 py-2 text-sm font-medium text-gray-300 bg-surface-raised hover:bg-gray-600 rounded-md transition-colors"
          >
            {{ $t('common.cancel') }}
          </button>
          <button
            type="submit"
            :disabled="loading"
            class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors disabled:opacity-50"
          >
            {{ loading ? $t('common.loading') : $t('common.save') }}
          </button>
        </div>
      </form>
    </div>

    <!-- Directory Browser -->
    <DirectoryBrowser
      v-if="showBrowser"
      :initial-path="form.path"
      @close="showBrowser = false"
      @select="handlePathSelect"
    />
  </ModalDialog>
</template>
