<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import ToastViewport from "@/components/ToastViewport.vue";
import { useUser } from "@/composables/useUser";
import { SESSION_EXPIRED_EVENT, safeReturnTo } from "@/services/authNavigation";

const { locale } = useI18n();
watch(locale, language => { document.documentElement.lang = language; }, { immediate: true });
const { loadUser, clearUser } = useUser();
const router = useRouter();
const route = useRoute();
function handleSessionExpired() {
  clearUser();
  if (route.name !== "login" && route.name !== "setup") {
    void router.replace({ name: "login", query: { reason: "expired", redirect: safeReturnTo(route.fullPath) } });
  }
}
window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
onUnmounted(() => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired));

// Load user information on app start if authenticated
onMounted(async () => {
  const user = await loadUser();
  if (user?.language) {
    locale.value = user.language;
  }
});
</script>

<template>
  <div class="min-h-screen bg-background">
    <a v-if="$route.name !== 'player'" href="#main-content" class="skip-link">{{ $t('common.skipToContent') }}</a>
    <router-view :key="$route.path" />
    <ToastViewport />
  </div>
</template>
