<script setup lang="ts">
import { computed, onMounted, onUnmounted, type Ref, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { auth, type Library, libraries as libraryApi } from "@/api/client";
import { useUser } from "@/composables/useUser";

const router = useRouter();
const route = useRoute();
const { isAdmin, clearUser, loadUser } = useUser();
const isDropdownOpen: Ref<boolean> = ref(false);
const dropdownContainer: Ref<HTMLElement | null> = ref(null);
const libraries: Ref<Library[]> = ref([]);

const isHomepage = computed(() => {
  return route.name === "home";
});

function isActiveLibrary(libraryId: string | number): boolean {
  return (
    route.name === "library" &&
    parseInt(route.params.id as string, 10) === parseInt(libraryId.toString(), 10)
  );
}

async function loadLibraries(): Promise<void> {
  try {
    libraries.value = await libraryApi.getLibraries();
  } catch (err) {
    console.error("Failed to load libraries:", err);
    libraries.value = [];
  }
}

function toggleDropdown(): void {
  isDropdownOpen.value = !isDropdownOpen.value;
}

function closeDropdown(): void {
  isDropdownOpen.value = false;
}

// Handle click outside dropdown
function handleClickOutside(event: Event): void {
  if (dropdownContainer.value && !dropdownContainer.value.contains(event.target as Node)) {
    closeDropdown();
  }
}

// Close dropdown on escape key
function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape" && isDropdownOpen.value) {
    closeDropdown();
  }
}

onMounted(async () => {
  document.addEventListener("click", handleClickOutside);
  document.addEventListener("keydown", handleEscape);
  // Load user data and libraries if authenticated but not yet loaded
  await Promise.all([loadUser(), loadLibraries()]);
});

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside);
  document.removeEventListener("keydown", handleEscape);
});

async function handleLogout(): Promise<void> {
  closeDropdown();
  try {
    await auth.logout();
    clearUser();
    router.push("/login");
  } catch (err) {
    console.error("Logout failed:", err);
    // Still clear user and redirect to login even if API call fails
    clearUser();
    router.push("/login");
  }
}
</script>

<template>
  <header class="bg-gray-900/95 backdrop-blur-xs sticky top-0 z-50 border-b border-gray-800">
    <div class="container mx-auto px-6 py-4 flex justify-between items-center">
      <div class="flex items-center space-x-6">
        <router-link
          to="/"
          class="text-3xl font-bold text-white hover:text-primary-400 transition-colors cursor-pointer"
        >
          {{ $t('common.appName') }}
        </router-link>
        <!-- Homepage link -->
        <router-link
          to="/"
          class="px-3 py-2 text-sm font-medium rounded-md transition-colors"
          :class="
            isHomepage
              ? 'text-white bg-primary-600 hover:bg-primary-700'
              : 'text-gray-300 hover:text-white hover:bg-gray-800'
          "
        >
          {{ $t('common.homepage') }}
        </router-link>
        <!-- Library links -->
        <router-link
          v-for="library in libraries"
          :key="library.id"
          :to="`/library/${library.id}`"
          class="px-3 py-2 text-sm font-medium rounded-md transition-colors"
          :class="
            isActiveLibrary(library.id)
              ? 'text-white bg-primary-600 hover:bg-primary-700'
              : 'text-gray-300 hover:text-white hover:bg-gray-800'
          "
        >
          {{ library.name }}
        </router-link>
      </div>
      <div class="flex items-center space-x-4">
        <!-- Dashboard button (admin only) -->
        <router-link
          v-if="isAdmin"
          to="/dashboard"
          class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors"
        >
          {{ $t('common.dashboard') }}
        </router-link>
        <div class="relative" ref="dropdownContainer">
          <button
            @click="toggleDropdown"
            class="flex items-center justify-center w-10 h-10 rounded-full bg-gray-700 hover:bg-gray-600 transition-colors focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-900 focus:ring-primary-500"
            :aria-expanded="isDropdownOpen"
            aria-label="User menu"
          >
            <svg
              class="w-6 h-6 text-gray-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
              />
            </svg>
          </button>

          <!-- Dropdown menu -->
          <transition
            enter-active-class="transition ease-out duration-100"
            enter-from-class="transform opacity-0 scale-95"
            enter-to-class="transform opacity-100 scale-100"
            leave-active-class="transition ease-in duration-75"
            leave-from-class="transform opacity-100 scale-100"
            leave-to-class="transform opacity-0 scale-95"
          >
            <div
              v-if="isDropdownOpen"
              class="absolute right-0 mt-2 w-48 rounded-md shadow-lg bg-gray-800 ring-1 ring-black ring-opacity-5 focus:outline-hidden"
            >
              <div class="py-1" role="menu" aria-orientation="vertical">
                <router-link
                  to="/settings"
                  @click="closeDropdown"
                  class="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
                  role="menuitem"
                >
                  <div class="flex items-center">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                      />
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                      />
                    </svg>
                    {{ $t('common.settings') }}
                  </div>
                </router-link>
                <button
                  @click="handleLogout"
                  class="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
                  role="menuitem"
                >
                  <div class="flex items-center">
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                      />
                    </svg>
                    {{ $t('common.logout') }}
                  </div>
                </button>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </div>
  </header>
</template>
