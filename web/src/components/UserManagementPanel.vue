<script setup lang="ts">
import { computed, onMounted, type Ref, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { dashboardUsers, getAccessToken, type User, type UserCreate, type UserUpdate } from "@/api/client";
import { useToast } from "@/composables/useToast";
import { useUser } from "@/composables/useUser";
import DashboardTable from "./DashboardTable.vue";
import ImageUploadEditor from "./ImageUploadEditor.vue";

type UserRole = "reader" | "admin";

interface UserForm {
  username: string;
  email: string;
  password: string;
  role: UserRole;
  is_active: boolean;
  language: string;
}

const { t } = useI18n();
const toast = useToast();
const { user: currentUser, loadUser, updateUser: updateCurrentUser } = useUser();

const users: Ref<User[]> = ref([]);
const loading = ref(false);
const saving = ref(false);
const deletingUserId = ref<number | null>(null);
const error = ref("");
const isModalOpen = ref(false);
const editingUser = ref<User | null>(null);
const profileUploader = ref<InstanceType<typeof ImageUploadEditor> | null>(null);
const hasPendingProfileImage = ref(false);
const shouldRemoveProfileImage = ref(false);

const form = reactive<UserForm>({
  username: "",
  email: "",
  password: "",
  role: "reader",
  is_active: true,
  language: "en",
});

const sortedUsers = computed(() =>
  [...users.value].sort((left, right) => left.username.localeCompare(right.username)),
);
const modalTitle = computed(() => (editingUser.value ? t("users.edit") : t("users.create")));
const modalAction = computed(() => (editingUser.value ? t("common.save") : t("users.createAction")));
const isEditingCurrentUser = computed(() => editingUser.value?.id === currentUser.value?.id);
const modalProfileImageUrl = computed(() => {
  if (shouldRemoveProfileImage.value) return null;
  return authenticatedProfileImageUrl(editingUser.value);
});

async function loadUsers(): Promise<void> {
  loading.value = true;
  error.value = "";

  try {
    users.value = await dashboardUsers.listUsers();
  } catch (err) {
    console.error("Failed to load users:", err);
    error.value = t("users.loadFailed");
  } finally {
    loading.value = false;
  }
}

function openCreateModal(): void {
  editingUser.value = null;
  resetForm();
  openModal();
}

function openEditModal(user: User): void {
  editingUser.value = user;
  form.username = user.username;
  form.email = user.email ?? "";
  form.password = "";
  form.role = user.role ?? (user.is_admin ? "admin" : "reader");
  form.is_active = user.is_active;
  form.language = user.language;
  openModal();
}

function openModal(): void {
  error.value = "";
  isModalOpen.value = true;
}

function closeModal(): void {
  if (saving.value) return;
  dismissModal();
}

function dismissModal(): void {
  isModalOpen.value = false;
  editingUser.value = null;
  resetForm();
  resetProfileImageForm();
}

async function submitForm(): Promise<void> {
  if (!form.username || (!editingUser.value && !form.password)) {
    error.value = t("users.requiredFields");
    return;
  }

  saving.value = true;
  error.value = "";

  try {
    let savedUser: User;
    if (editingUser.value) {
      savedUser = await dashboardUsers.updateUser(editingUser.value.id, buildUpdatePayload());
    } else {
      savedUser = await dashboardUsers.createUser(buildCreatePayload());
    }

    savedUser = await saveProfileImageChanges(savedUser);
    upsertUser(savedUser);
    toast.success(editingUser.value ? t("users.updateSuccess") : t("users.createSuccess"));
    dismissModal();
  } catch (err) {
    console.error("Failed to save user:", err);
    const message = editingUser.value ? t("users.updateFailed") : t("users.createFailed");
    error.value = message;
    toast.error(message);
  } finally {
    saving.value = false;
  }
}

async function deleteUser(user: User): Promise<void> {
  if (isCurrentUser(user)) {
    toast.warn(t("users.currentAdminDeleteLocked"));
    return;
  }

  if (!window.confirm(t("users.confirmDelete", { username: user.username }))) {
    return;
  }

  deletingUserId.value = user.id;
  error.value = "";

  try {
    await dashboardUsers.deleteUser(user.id);
    users.value = users.value.filter((item) => item.id !== user.id);
    toast.success(t("users.deleteSuccess"));
  } catch (err) {
    console.error("Failed to delete user:", err);
    toast.error(t("users.deleteFailed"));
  } finally {
    deletingUserId.value = null;
  }
}

function buildCreatePayload(): UserCreate {
  return {
    username: form.username.trim(),
    email: normalizedEmail(form.email),
    password: form.password,
    role: form.role,
    is_admin: form.role === "admin",
    language: form.language,
  };
}

function buildUpdatePayload(): UserUpdate {
  return {
    username: form.username.trim(),
    email: normalizedEmail(form.email),
    password: form.password || undefined,
    role: form.role,
    is_admin: form.role === "admin",
    is_active: form.is_active,
    language: form.language,
  };
}

function resetForm(): void {
  form.username = "";
  form.email = "";
  form.password = "";
  form.role = "reader";
  form.is_active = true;
  form.language = "en";
}

function resetProfileImageForm(): void {
  hasPendingProfileImage.value = false;
  shouldRemoveProfileImage.value = false;
}

function normalizedEmail(email: string): string | null {
  const value = email.trim();
  return value || null;
}

function roleLabel(role: UserRole): string {
  return t(`users.roles.${role}`);
}

function statusLabel(user: User): string {
  return user.is_active ? t("users.active") : t("users.inactive");
}

function isCurrentUser(user: User): boolean {
  return user.id === currentUser.value?.id;
}

function authenticatedProfileImageUrl(user: User | null): string | null {
  if (!user?.profile_image_url) return null;
  const token = getAccessToken();
  if (!token) return user.profile_image_url;

  const url = new URL(user.profile_image_url, window.location.origin);
  url.searchParams.set("api_key", token);
  return `${url.pathname}${url.search}`;
}

function userInitial(user: User | null): string {
  return (user?.username || form.username || "?").slice(0, 1).toUpperCase();
}

function markProfileImageSelected(): void {
  hasPendingProfileImage.value = true;
  shouldRemoveProfileImage.value = false;
}

function removeProfileImage(): void {
  hasPendingProfileImage.value = false;
  shouldRemoveProfileImage.value = true;
}

async function saveProfileImageChanges(user: User): Promise<User> {
  if (hasPendingProfileImage.value) {
    const editedFile = await profileUploader.value?.getEditedFile();
    if (editedFile) {
      return await dashboardUsers.uploadProfileImage(user.id, editedFile);
    }
  }
  if (editingUser.value && shouldRemoveProfileImage.value && user.profile_image_url) {
    return await dashboardUsers.deleteProfileImage(user.id);
  }
  return user;
}

function upsertUser(user: User): void {
  const exists = users.value.some((item) => item.id === user.id);
  users.value = exists ? users.value.map((item) => (item.id === user.id ? user : item)) : [...users.value, user];
  if (currentUser.value?.id === user.id) {
    updateCurrentUser(user);
  }
}

onMounted(async () => {
  await Promise.all([loadUser(), loadUsers()]);
});
</script>

<template>
  <section class="space-y-6">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 class="text-3xl font-bold text-white">{{ t("users.title") }}</h1>
        <p class="mt-1 text-sm text-gray-400">{{ t("users.subtitle") }}</p>
      </div>
      <button
        type="button"
        class="inline-flex items-center justify-center gap-2 rounded-md bg-primary-600 px-4 py-2 font-semibold text-white transition-colors hover:bg-primary-700"
        @click="openCreateModal"
      >
        <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m7-7H5" />
        </svg>
        {{ t("users.createAction") }}
      </button>
    </div>

    <div v-if="error && !isModalOpen" class="rounded-md border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-200">
      {{ error }}
    </div>
    <DashboardTable scrollable>
      <thead class="bg-gray-900/70">
        <tr>
          <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("users.profileImage") }}
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("users.username") }}
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("users.email") }}
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("users.role") }}
          </th>
          <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("users.status") }}
          </th>
          <th class="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-gray-400">
            {{ t("common.actions") }}
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-700">
        <tr v-if="loading">
          <td colspan="6" class="px-4 py-8 text-center text-gray-400">{{ t("common.loading") }}</td>
        </tr>
        <tr v-else-if="sortedUsers.length === 0">
          <td colspan="6" class="px-4 py-8 text-center text-gray-400">{{ t("users.empty") }}</td>
        </tr>
        <tr v-for="user in sortedUsers" v-else :key="user.id" class="bg-gray-800">
          <td class="px-4 py-4">
            <div class="flex h-11 w-11 items-center justify-center overflow-hidden rounded-full bg-gray-700 text-sm font-semibold text-gray-200">
              <img
                v-if="authenticatedProfileImageUrl(user)"
                :src="authenticatedProfileImageUrl(user) || undefined"
                :alt="user.username"
                class="h-full w-full object-cover"
              />
              <span v-else>{{ userInitial(user) }}</span>
            </div>
          </td>
          <td class="px-4 py-4">
            <div class="font-medium text-white">{{ user.username }}</div>
            <div class="text-xs text-gray-500">#{{ user.id }}</div>
          </td>
          <td class="px-4 py-4 text-sm text-gray-300">
            {{ user.email || "-" }}
          </td>
          <td class="px-4 py-4">
            <span
              class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold"
              :class="user.is_admin ? 'bg-primary-500/20 text-primary-200' : 'bg-gray-700 text-gray-200'"
            >
              {{ roleLabel(user.role ?? (user.is_admin ? "admin" : "reader")) }}
            </span>
          </td>
          <td class="px-4 py-4">
            <span
              class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold"
              :class="user.is_active ? 'bg-green-500/15 text-green-200' : 'bg-red-500/15 text-red-200'"
            >
              {{ statusLabel(user) }}
            </span>
          </td>
          <td class="px-4 py-4">
            <div class="flex justify-end gap-2">
              <button
                type="button"
                class="inline-flex h-9 w-9 items-center justify-center rounded-md bg-gray-700 text-gray-200 transition-colors hover:bg-gray-600 hover:text-white"
                :aria-label="t('common.edit')"
                :title="t('common.edit')"
                @click="openEditModal(user)"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M15.232 5.232l3.536 3.536M4 20h4.586a1 1 0 00.707-.293l9.9-9.9a2.5 2.5 0 00-3.536-3.536l-9.9 9.9A1 1 0 005.464 16.879L4 20z"
                  />
                </svg>
              </button>
              <button
                type="button"
                class="inline-flex h-9 w-9 items-center justify-center rounded-md bg-red-800/80 text-red-100 transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                :aria-label="t('common.delete')"
                :title="isCurrentUser(user) ? t('users.currentAdminDeleteLocked') : t('common.delete')"
                :disabled="deletingUserId === user.id || isCurrentUser(user)"
                @click="deleteUser(user)"
              >
                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7h6m-7 0a1 1 0 001-1h6a1 1 0 001 1m-8 0h8"
                  />
                </svg>
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </DashboardTable>

    <teleport to="body">
      <div
        v-if="isModalOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
        role="dialog"
        aria-modal="true"
        @click.self="closeModal"
      >
        <form class="w-full max-w-xl rounded-lg bg-gray-800 p-6 shadow-2xl" @submit.prevent="submitForm">
          <div class="flex items-start justify-between gap-4">
            <h2 class="text-xl font-semibold text-white">{{ modalTitle }}</h2>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
              :aria-label="t('common.cancel')"
              @click="closeModal"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div v-if="error" class="mt-4 rounded-md border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-200">
            {{ error }}
          </div>

          <div class="mt-5">
            <ImageUploadEditor
              ref="profileUploader"
              :current-image-url="modalProfileImageUrl"
              :fallback-initial="userInitial(editingUser)"
              mask="circle"
              :aspect-ratio="1"
              @selected="markProfileImageSelected"
              @remove="removeProfileImage"
            />
          </div>

          <div class="mt-5 grid gap-4 sm:grid-cols-2">
            <label class="block">
              <span class="text-sm text-gray-300">{{ t("users.username") }}</span>
              <input
                v-model="form.username"
                class="mt-1 w-full rounded-md border border-gray-600 bg-gray-900 px-3 py-2 text-white focus:border-primary-500 focus:outline-none"
                type="text"
                autocomplete="off"
              />
            </label>
            <label class="block">
              <span class="text-sm text-gray-300">{{ t("users.email") }}</span>
              <input
                v-model="form.email"
                class="mt-1 w-full rounded-md border border-gray-600 bg-gray-900 px-3 py-2 text-white focus:border-primary-500 focus:outline-none"
                type="email"
                autocomplete="off"
              />
            </label>
            <label class="block">
              <span class="text-sm text-gray-300">{{ t("users.password") }}</span>
              <input
                v-model="form.password"
                class="mt-1 w-full rounded-md border border-gray-600 bg-gray-900 px-3 py-2 text-white focus:border-primary-500 focus:outline-none"
                type="password"
                autocomplete="new-password"
                :placeholder="editingUser ? t('users.passwordPlaceholder') : undefined"
              />
            </label>
            <label class="block">
              <span class="text-sm text-gray-300">{{ t("users.role") }}</span>
              <div
                v-if="isEditingCurrentUser"
                class="mt-1 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-gray-300"
              >
                {{ roleLabel(form.role) }}
              </div>
              <select
                v-else
                v-model="form.role"
                class="mt-1 w-full rounded-md border border-gray-600 bg-gray-900 px-3 py-2 text-white focus:border-primary-500 focus:outline-none"
              >
                <option value="reader">{{ roleLabel("reader") }}</option>
                <option value="admin">{{ roleLabel("admin") }}</option>
              </select>
            </label>
            <label class="block">
              <span class="text-sm text-gray-300">{{ t("users.language") }}</span>
              <select
                v-model="form.language"
                class="mt-1 w-full rounded-md border border-gray-600 bg-gray-900 px-3 py-2 text-white focus:border-primary-500 focus:outline-none"
              >
                <option value="en">English</option>
                <option value="fr">Français</option>
              </select>
            </label>
            <label v-if="editingUser && !isEditingCurrentUser" class="flex items-end gap-2 pb-2 text-sm text-gray-200">
              <input
                v-model="form.is_active"
                type="checkbox"
                class="h-4 w-4 rounded border-gray-600 bg-gray-900 text-primary-600 focus:ring-primary-500"
              />
              {{ form.is_active ? t("users.active") : t("users.inactive") }}
            </label>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <button
              type="button"
              class="rounded-md bg-gray-700 px-4 py-2 font-medium text-gray-100 transition-colors hover:bg-gray-600"
              @click="closeModal"
            >
              {{ t("common.cancel") }}
            </button>
            <button
              type="submit"
              class="rounded-md bg-primary-600 px-4 py-2 font-semibold text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="saving"
            >
              {{ saving ? t("users.saving") : modalAction }}
            </button>
          </div>
        </form>
      </div>
    </teleport>
  </section>
</template>
