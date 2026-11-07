<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { auth, type User } from "@/api/client";

const props = defineProps<{user:User}>();
const emit = defineEmits<{saved:[user:User]}>();
const { t, locale } = useI18n();
const audioLanguage = ref(props.user.preferred_audio_language || "");
const subtitleLanguage = ref(props.user.preferred_subtitle_language || "");
const subtitleMode = ref<User["subtitle_mode"]>(props.user.subtitle_mode || "off");
const pending = ref(false);
const error = ref("");
const saved = ref(false);
const languageCodes = "aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu".split(" ");
const languages = computed(() => {
  const names = new Intl.DisplayNames([locale.value], {type:"language"});
  const codes = new Set([...languageCodes, audioLanguage.value, subtitleLanguage.value].filter(Boolean));
  return [...codes].map(value => {
    let label = value;
    try { label = names.of(value) || value; } catch { /* Preserve unfamiliar stored language codes. */ }
    return {value, label};
  }).sort((a,b) => a.label.localeCompare(b.label, locale.value));
});
async function save() {
  if (pending.value) return;
  pending.value = true;
  saved.value = false;
  error.value = "";
  try {
    const user = await auth.updateCurrentUser({preferred_audio_language:audioLanguage.value || null, preferred_subtitle_language:subtitleLanguage.value || null, subtitle_mode:subtitleMode.value});
    emit("saved", user);
    saved.value = true;
  } catch { error.value = t("preferences.saveFailed"); }
  finally { pending.value = false; }
}
</script>

<template>
  <form class="surface-panel space-y-6 p-6 sm:p-8" :aria-busy="pending" @submit.prevent="save" @change="saved = false">
    <div><h2 class="text-xl font-semibold">{{ $t('preferences.title') }}</h2><p class="mt-2 text-sm leading-6 text-muted">{{ $t('preferences.description') }}</p></div>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <div class="space-y-2"><label for="preferred-audio" class="field-label">{{ $t('preferences.audioLanguage') }}</label><select id="preferred-audio" v-model="audioLanguage" class="field-input"><option value="">{{ $t('preferences.defaultTrack') }}</option><option v-for="language in languages" :key="language.value" :value="language.value">{{ language.label }}</option></select></div>
    <div class="space-y-2"><label for="subtitle-mode" class="field-label">{{ $t('preferences.subtitleMode') }}</label><select id="subtitle-mode" v-model="subtitleMode" class="field-input"><option value="off">{{ $t('preferences.off') }}</option><option value="forced">{{ $t('preferences.forced') }}</option><option value="always">{{ $t('preferences.always') }}</option></select><p class="text-xs leading-relaxed text-muted">{{ $t('preferences.forcedHelp') }}</p></div>
    <div v-if="subtitleMode !== 'off'" class="space-y-2"><label for="preferred-subtitle" class="field-label">{{ $t('preferences.subtitleLanguage') }}</label><select id="preferred-subtitle" v-model="subtitleLanguage" class="field-input"><option value="">{{ $t('preferences.defaultTrack') }}</option><option v-for="language in languages" :key="language.value" :value="language.value">{{ language.label }}</option></select></div>
    <p class="text-xs leading-relaxed text-muted">{{ $t('preferences.fallback') }}</p>
    <p v-if="saved" role="status" class="text-sm text-emerald-300">{{ $t('preferences.saved') }}</p>
    <button type="submit" :disabled="pending" class="button-secondary w-full">{{ pending ? $t('common.loading') : $t('common.save') }}</button>
  </form>
</template>
