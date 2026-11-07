<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { auth } from "@/api/client";
import AuthLayout from "@/components/auth/AuthLayout.vue";
import PasswordField from "@/components/auth/PasswordField.vue";
import { useUser } from "@/composables/useUser";
import { safeReturnTo } from "@/services/authNavigation";

const { t, locale } = useI18n();
const { updateUser } = useUser();
const router = useRouter();
const route = useRoute();
const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");
const notice = computed(() => route.query.reason === "expired" ? t("auth.sessionExpired") : route.query.reason === "password-changed" ? t("auth.passwordChanged") : "");

onMounted(async () => {
  try {
    const status = await auth.checkSetupStatus();
    if (status && !status.setup_complete) await router.replace("/setup");
  } catch { /* A temporary status failure must not prevent login. */ }
});

async function handleLogin() {
  if (loading.value) return;
  error.value = "";
  loading.value = true;
  try {
    await auth.login(username.value.trim(), password.value, navigator.userAgent);
    const user = await auth.getCurrentUser();
    updateUser(user);
    if (user.language) locale.value = user.language;
    await router.replace(safeReturnTo(route.query.redirect));
  } catch (cause) {
    const status = cause && typeof cause === "object" && "status" in cause ? cause.status : undefined;
    error.value = t(status === 401 || status === 403 ? "login.failed" : "auth.unavailable");
    if (status === 401 || status === 403) document.getElementById("username")?.focus();
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout :title="$t('login.title')" :subtitle="$t('auth.accountHelp')">
    <p v-if="notice" role="status" class="mb-6 rounded-xl border border-primary-400/20 bg-primary-500/10 p-4 text-sm leading-6 text-primary-200">{{ notice }}</p>
    <form class="space-y-6" :aria-busy="loading" @submit.prevent="handleLogin">
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <div class="space-y-2">
        <label for="username" class="field-label">{{ $t('login.username') }}</label>
        <input id="username" v-model="username" name="username" type="text" autocomplete="username" autocapitalize="none" :spellcheck="false" required class="field-input" />
      </div>
      <PasswordField id="password" v-model="password" :label="$t('login.password')" autocomplete="current-password" required />
      <button type="submit" :disabled="loading" class="button-primary w-full">
        <span v-if="loading" class="size-4 animate-spin rounded-full border-2 border-white/30 border-t-white" aria-hidden="true"></span>
        {{ loading ? $t('login.signingIn') : $t('login.signIn') }}
      </button>
    </form>
  </AuthLayout>
</template>
