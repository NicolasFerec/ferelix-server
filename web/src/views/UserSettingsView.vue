<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { auth, type UserUpdate } from "@/api/client";
import MenuBar from "../components/MenuBar.vue";

const { locale, t } = useI18n();
const router = useRouter();

const loading = ref(true);
const submitting = ref(false);
const error = ref("");
const success = ref(false);
const formData = ref({
  username: "",
  email: "",
  password: "",
  confirmPassword: "",
  language: "en",
});

async function loadUserData() {
  loading.value = true;
  error.value = "";

  try {
    const user = await auth.getCurrentUser();
    formData.value.username = user.username;
    formData.value.email = user.email;
    formData.value.language = user.language || "en";
    // Set i18n locale based on user preference
    locale.value = user.language || "en";
  } catch (err: unknown) {
    console.error("Failed to load user data:", err);
    const apiErr = err as { data?: { detail?: string } };
    error.value = apiErr.data?.detail || t("settings.updateFailed");
  } finally {
    loading.value = false;
  }
}

async function handleSubmit() {
  error.value = "";
  success.value = false;

  // Validate password match if password is provided
  if (formData.value.password && formData.value.password !== formData.value.confirmPassword) {
    error.value = t("settings.passwordMismatch");
    return;
  }

  submitting.value = true;

  try {
    const updateData: UserUpdate = {
      username: formData.value.username,
      email: formData.value.email || null,
      language: formData.value.language,
    };

    // Only include password if it's provided
    if (formData.value.password) {
      updateData.password = formData.value.password;
    }

    await auth.updateCurrentUser(updateData);

    // Update i18n locale
    locale.value = formData.value.language;

    success.value = true;

    // Clear password fields
    formData.value.password = "";
    formData.value.confirmPassword = "";

    // Hide success message after 3 seconds
    setTimeout(() => {
      success.value = false;
    }, 3000);
  } catch (err: unknown) {
    console.error("Failed to update user:", err);
    const apiErr = err as { data?: { detail?: string } };
    error.value = apiErr.data?.detail || t("settings.updateFailed");
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  loadUserData();
});
</script>

<template>
  <div class="min-h-screen bg-gray-900">
    <MenuBar />

    <main class="container mx-auto px-6 py-8 max-w-2xl">
      <h2 class="text-2xl font-semibold mb-6 text-white">{{ $t('settings.title') }}</h2>

      <div v-if="loading" class="text-center text-gray-400 py-12">
        {{ $t('common.loading') }}
      </div>

      <form v-else class="space-y-6" @submit.prevent="handleSubmit">
        <div v-if="error" class="rounded-md bg-red-900 bg-opacity-50 p-4">
          <div class="flex">
            <div class="ml-3">
              <h3 class="text-sm font-medium text-red-300">
                {{ error }}
              </h3>
            </div>
          </div>
        </div>

        <div v-if="success" class="rounded-md bg-green-900 bg-opacity-50 p-4">
          <div class="flex">
            <div class="ml-3">
              <h3 class="text-sm font-medium text-green-300">
                {{ $t('settings.updateSuccess') }}
              </h3>
            </div>
          </div>
        </div>

        <div class="space-y-4">
          <div>
            <label for="username" class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.username') }}
            </label>
            <input
              id="username"
              v-model="formData.username"
              name="username"
              type="text"
              required
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
            />
          </div>

          <div>
            <label for="email" class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.email') }}
            </label>
            <input
              id="email"
              v-model="formData.email"
              name="email"
              type="email"
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
            />
          </div>

          <div>
            <label for="password" class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.password') }}
            </label>
            <input
              id="password"
              v-model="formData.password"
              name="password"
              type="password"
              autocomplete="new-password"
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
              :placeholder="$t('settings.leaveEmpty')"
            />
          </div>

          <div v-if="formData.password">
            <label for="confirmPassword" class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.confirmPassword') }}
            </label>
            <input
              id="confirmPassword"
              v-model="formData.confirmPassword"
              name="confirmPassword"
              type="password"
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 placeholder-gray-500 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
            />
          </div>

          <div>
            <label for="language" class="block text-sm font-medium text-gray-300 mb-2">
              {{ $t('settings.language') }}
            </label>
            <select
              id="language"
              v-model="formData.language"
              name="language"
              class="appearance-none relative block w-full px-3 py-2 border border-gray-700 text-white bg-gray-800 rounded-md focus:outline-hidden focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
            >
              <option value="en">English</option>
              <option value="fr">Français</option>
            </select>
          </div>
        </div>

        <div class="flex gap-4">
          <button
            type="submit"
            :disabled="submitting"
            class="flex-1 flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ submitting ? $t('common.loading') : $t('common.save') }}
          </button>
          <router-link
            to="/"
            class="flex-1 flex justify-center py-2 px-4 border border-gray-700 text-sm font-medium rounded-md text-gray-300 bg-gray-800 hover:bg-gray-700 focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            {{ $t('common.cancel') }}
          </router-link>
        </div>
      </form>
    </main>
  </div>
</template>
