<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { watchlist } from "@/api/client";

const props = defineProps<{mediaId:number; inWatchlist:boolean}>();
const emit = defineEmits<{updated:[value:boolean]}>();
const { t } = useI18n();
const pending = ref(false);
const error = ref("");
async function toggle() {
  if (pending.value) return;
  pending.value = true;
  error.value = "";
  try {
    const result = props.inWatchlist ? await watchlist.remove(props.mediaId) : await watchlist.add(props.mediaId);
    emit("updated", result.in_watchlist);
  } catch { error.value = t("watchlist.updateFailed"); }
  finally { pending.value = false; }
}
</script>

<template>
  <div>
    <button type="button" :disabled="pending" :aria-pressed="inWatchlist" :aria-busy="pending" class="button-secondary" @click="toggle">
      <svg aria-hidden="true" class="size-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path :d="inWatchlist ? 'm5 12 4 4L19 6' : 'M12 5v14M5 12h14'" /></svg>
      {{ pending ? $t('common.loading') : $t(inWatchlist ? 'watchlist.remove' : 'watchlist.add') }}
    </button>
    <p v-if="error" role="alert" class="mt-3 max-w-sm text-sm text-red-200">{{ error }}</p>
  </div>
</template>
