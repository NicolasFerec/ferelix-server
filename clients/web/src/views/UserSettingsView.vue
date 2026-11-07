<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { auth, clearTokens, getAccessToken, type User } from "@/api/client";
import PasswordField from "@/components/auth/PasswordField.vue";
import ImageUploadEditor from "@/components/ImageUploadEditor.vue";
import MenuBar from "@/components/MenuBar.vue";
import { useToast } from "@/composables/useToast";
import { useUser } from "@/composables/useUser";

const { locale, t } = useI18n();
const router = useRouter();
const toast = useToast();
const { user, updateUser, clearUser } = useUser();
const loading = ref(true);
const submitting = ref(false);
const error = ref("");
const profileUploader = ref<InstanceType<typeof ImageUploadEditor> | null>(null);
const hasPendingImage = ref(false);
const removeImage = ref(false);
const form = ref({ username: "", email: "", language: "en" });
const passwordForm = ref({ current: "", password: "", confirm: "" });
const passwordError = ref("");
const changingPassword = ref(false);
const profileImageUrl = computed(() => removeImage.value ? null : authenticatedImage(user.value));
function authenticatedImage(value: User | null) {
  if (!value?.profile_image_url) return null;
  const url = new URL(value.profile_image_url, window.location.origin);
  const token = getAccessToken();
  if (token) url.searchParams.set("api_key", token);
  return `${url.pathname}${url.search}`;
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const value = await auth.getCurrentUser();
    updateUser(value);
    form.value = { username: value.username, email: value.email || "", language: value.language || "en" };
  } catch { error.value = t("settings.updateFailed"); }
  finally { loading.value = false; }
}
async function saveProfile() {
  if (submitting.value) return;
  submitting.value = true;
  error.value = "";
  try {
    let saved = await auth.updateCurrentUser({ username: form.value.username.trim(), email: form.value.email || null, language: form.value.language });
    if (hasPendingImage.value) {
      const file = await profileUploader.value?.getEditedFile();
      if (file) saved = await auth.uploadCurrentUserProfileImage(file);
    } else if (removeImage.value && saved.profile_image_url) saved = await auth.deleteCurrentUserProfileImage();
    updateUser(saved);
    locale.value = form.value.language;
    hasPendingImage.value = false;
    removeImage.value = false;
    profileUploader.value?.resetSelection();
    toast.success(t("settings.updateSuccess"));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t("settings.updateFailed");
  } finally { submitting.value = false; }
}
async function changePassword() {
  if (changingPassword.value) return;
  passwordError.value = "";
  if (passwordForm.value.password !== passwordForm.value.confirm) {
    passwordError.value = t("settings.passwordMismatch");
    document.getElementById("confirm-password")?.focus();
    return;
  }
  changingPassword.value = true;
  try {
    await auth.updateCurrentUser({ password: passwordForm.value.password, current_password: passwordForm.value.current });
    clearTokens();
    clearUser();
    await router.replace({ name: "login", query: { reason: "password-changed", redirect: "/settings" } });
  } catch {
    passwordError.value = t("auth.passwordChangeFailed");
    document.getElementById("current-password")?.focus();
  } finally { changingPassword.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="min-h-screen bg-background">
    <MenuBar />
    <main id="main-content" class="page-shell max-w-5xl">
      <h1 class="page-heading mb-8">{{ $t('settings.title') }}</h1>
      <p v-if="loading" role="status" class="empty-state">{{ $t('common.loading') }}</p>
      <div v-else class="grid gap-8 lg:grid-cols-2 lg:items-start">
        <form class="surface-panel space-y-6 p-6 sm:p-8" :aria-busy="submitting" @submit.prevent="saveProfile">
          <h2 class="text-xl font-semibold">{{ $t('settings.profile') }}</h2>
          <p v-if="error" role="alert" class="form-error">{{ error }}</p>
          <div>
            <p class="field-label mb-3">{{ $t('users.profileImage') }}</p>
            <ImageUploadEditor ref="profileUploader" :current-image-url="profileImageUrl" :fallback-initial="(user?.username || '?').slice(0, 1).toUpperCase()" mask="circle" :aspect-ratio="1" @selected="hasPendingImage = true; removeImage = false" @remove="hasPendingImage = false; removeImage = true" />
          </div>
          <div class="space-y-2"><label for="username" class="field-label">{{ $t('settings.username') }}</label><input id="username" v-model="form.username" name="username" autocomplete="username" :spellcheck="false" required class="field-input" /></div>
          <div class="space-y-2"><label for="email" class="field-label">{{ $t('settings.email') }}</label><input id="email" v-model="form.email" name="email" type="email" autocomplete="email" :spellcheck="false" class="field-input" /></div>
          <div class="space-y-2"><label for="language" class="field-label">{{ $t('settings.language') }}</label><select id="language" v-model="form.language" name="language" autocomplete="language" class="field-input"><option value="en">English</option><option value="fr">Français</option></select></div>
          <button type="submit" :disabled="submitting" class="button-primary w-full">{{ submitting ? $t('common.loading') : $t('common.save') }}</button>
        </form>
        <form class="surface-panel space-y-6 p-6 sm:p-8" :aria-busy="changingPassword" @submit.prevent="changePassword">
          <div><h2 class="text-xl font-semibold">{{ $t('auth.security') }}</h2><p class="mt-2 text-sm leading-6 text-muted">{{ $t('auth.securityDescription') }}</p></div>
          <p v-if="passwordError" role="alert" class="form-error">{{ passwordError }}</p>
          <PasswordField id="current-password" v-model="passwordForm.current" :label="$t('auth.currentPassword')" autocomplete="current-password" required />
          <PasswordField id="new-password" v-model="passwordForm.password" :label="$t('settings.password')" autocomplete="new-password" required />
          <PasswordField id="confirm-password" v-model="passwordForm.confirm" :label="$t('settings.confirmPassword')" autocomplete="new-password" required />
          <button type="submit" :disabled="changingPassword" class="button-secondary w-full">{{ changingPassword ? $t('common.loading') : $t('auth.changePassword') }}</button>
        </form>
      </div>
    </main>
  </div>
</template>
