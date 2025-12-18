<script setup lang="ts">
import { onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { auth } from "@/api/client";
import { useUser } from "@/composables/useUser";

const { t } = useI18n();

const router = useRouter();
const { loadUser } = useUser();

const username: Ref<string> = ref("");
const password: Ref<string> = ref("");
const confirmPassword: Ref<string> = ref("");
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");

// Detect browser language
function detectBrowserLanguage(): string {
  const browserLang =
    navigator.language || (navigator as Navigator & { userLanguage?: string }).userLanguage || "en";
  const langCode = browserLang.split("-")[0].toLowerCase();

  // Supported languages: en, fr
  if (langCode === "fr") {
    return "fr";
  }

  // Default to English
  return "en";
}

const browserLanguage: Ref<string> = ref("en");

onMounted(() => {
  browserLanguage.value = detectBrowserLanguage();
});

async function handleSetup(): Promise<void> {
  error.value = "";

  // Validate password match
  if (password.value !== confirmPassword.value) {
    error.value = t("setup.passwordMismatch");
    return;
  }

  loading.value = true;

  try {
    await auth.createAdmin(username.value, password.value, browserLanguage.value);
    // Load user data so the menu bar shows the dashboard button
    await loadUser();
    router.push("/");
  } catch (err: unknown) {
    console.error("Setup failed:", err);
    const apiErr = err as { data?: { detail?: string } };
    error.value = apiErr.data?.detail || t("setup.failed");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 flex items-center justify-center px-4">
    <div class="max-w-md w-full space-y-8">
      <div>
        <h2 class="mt-6 text-center text-3xl font-extrabold text-white">
          {{ $t('setup.title') }}
        </h2>
        <p class="mt-2 text-center text-sm text-gray-400">
          {{ $t('setup.subtitle') }}
        </p>
      </div>

      <form class="mt-8 space-y-6" @submit.prevent="handleSetup">
        <div v-if="error" class="rounded-md bg-red-900 bg-opacity-50 p-4">
          <div class="flex">
            <div class="ml-3">
              <h3 class="text-sm font-medium text-red-300">
                {{ error }}
              </h3>
            </div>
          </div>
        </div>

        <div class="rounded-md shadow-xs space-y-3">
          <div>
            <label for="username" class="sr-only">Username</label>
            <input
              id="username"
              v-model="username"
              name="username"
              type="text"
              required
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 focus:z-10 sm:text-sm"
              :placeholder="$t('setup.username')"
            />
          </div>
          <div>
            <label for="password" class="sr-only">Password</label>
            <input
              id="password"
              v-model="password"
              name="password"
              type="password"
              required
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 focus:z-10 sm:text-sm"
              :placeholder="$t('setup.password')"
            />
          </div>
          <div>
            <label for="confirmPassword" class="sr-only">Confirm Password</label>
            <input
              id="confirmPassword"
              v-model="confirmPassword"
              name="confirmPassword"
              type="password"
              required
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 focus:z-10 sm:text-sm"
              :placeholder="$t('setup.confirmPassword')"
            />
          </div>
        </div>

        <div>
          <button
            type="submit"
            :disabled="loading"
            class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ loading ? $t('setup.creating') : $t('setup.createAccount') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
