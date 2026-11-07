<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { auth } from "@/api/client";
import AuthLayout from "@/components/auth/AuthLayout.vue";
import PasswordField from "@/components/auth/PasswordField.vue";
import { useUser } from "@/composables/useUser";

const { t } = useI18n();
const router = useRouter();
const { loadUser } = useUser();
const username = ref("");
const password = ref("");
const confirmPassword = ref("");
const loading = ref(false);
const error = ref("");

onMounted(async () => {
  const status = await auth.checkSetupStatus().catch(() => null);
  if (status?.setup_complete) await router.replace("/login");
});

async function handleSetup() {
  if (loading.value) return;
  error.value = "";
  if (password.value !== confirmPassword.value) {
    error.value = t("setup.passwordMismatch");
    document.getElementById("confirmPassword")?.focus();
    return;
  }
  loading.value = true;
  try {
    const language = navigator.language.toLowerCase().startsWith("fr") ? "fr" : "en";
    await auth.createAdmin(username.value.trim(), password.value, language);
    await loadUser();
    await router.replace("/");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("setup.failed");
  } finally { loading.value = false; }
}
</script>

<template>
  <AuthLayout :title="$t('setup.title')" :subtitle="$t('setup.subtitle')">
    <form class="space-y-5" :aria-busy="loading" @submit.prevent="handleSetup">
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <div class="space-y-2">
        <label for="username" class="field-label">{{ $t('setup.username') }}</label>
        <input id="username" v-model="username" name="username" autocomplete="username" autocapitalize="none" :spellcheck="false" required class="field-input" />
      </div>
      <PasswordField id="password" v-model="password" :label="$t('setup.password')" autocomplete="new-password" required />
      <PasswordField id="confirmPassword" v-model="confirmPassword" :label="$t('setup.confirmPassword')" autocomplete="new-password" required />
      <button type="submit" :disabled="loading" class="button-primary w-full">{{ loading ? $t('setup.creating') : $t('setup.createAccount') }}</button>
    </form>
  </AuthLayout>
</template>
