<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, type Ref, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { auth, getAccessToken, type Library, libraries as libraryApi } from "@/api/client";
import { useUser } from "@/composables/useUser";

const router = useRouter();
const route = useRoute();
const { t } = useI18n();
const { user: currentUser, isAdmin, clearUser, loadUser } = useUser();
const isDropdownOpen: Ref<boolean> = ref(false);
const isMobileNavigationOpen = ref(false);
const isMobileViewport = ref(false);
const hasNavigationOverflow = ref(false);
const canScrollNavigationLeft = ref(false);
const canScrollNavigationRight = ref(false);
const dropdownContainer: Ref<HTMLElement | null> = ref(null);
const navigationScroller: Ref<HTMLElement | null> = ref(null);
const libraries: Ref<Library[]> = ref([]);
let resizeObserver: ResizeObserver | null = null;
let observedNavigationScroller: HTMLElement | null = null;

const isHomepage = computed(() => {
  return route.name === "home";
});

const navigationItems = computed(() => [
  {
    id: "home",
    label: t("common.homepage"),
    to: "/",
    active: isHomepage.value,
  },
  ...libraries.value.map((library) => ({
    id: `library-${library.id}`,
    label: library.name,
    to: `/library/${library.id}`,
    active: isActiveLibrary(library.id),
  })),
]);

const activeLibraryId = computed(() => {
  if (route.name === "library") {
    return parseRouteId(route.params.id);
  }

  if (route.name === "media-detail") {
    return parseRouteId(route.query.libraryId);
  }

  return null;
});

const userProfileImageUrl = computed(() => {
  if (!currentUser.value?.profile_image_url) return null;
  const token = getAccessToken();
  if (!token) return currentUser.value.profile_image_url;

  const url = new URL(currentUser.value.profile_image_url, window.location.origin);
  url.searchParams.set("api_key", token);
  return `${url.pathname}${url.search}`;
});

const userInitials = computed(() => {
  const username = currentUser.value?.username?.trim();
  if (!username) return "?";

  const parts = username.split(/[\s._-]+/).filter(Boolean);
  const initials = parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : username.slice(0, 2);
  return initials.toUpperCase();
});

function parseRouteId(value: unknown): number | null {
  const routeId = Array.isArray(value) ? value[0] : value;
  if (typeof routeId !== "string" && typeof routeId !== "number") return null;

  const parsed = parseInt(routeId.toString(), 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function isActiveLibrary(libraryId: string | number): boolean {
  return activeLibraryId.value === parseInt(libraryId.toString(), 10);
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

function toggleMobileNavigation(): void {
  isMobileNavigationOpen.value = !isMobileNavigationOpen.value;
  closeDropdown();
}

function closeMobileNavigation(): void {
  isMobileNavigationOpen.value = false;
}

function updateNavigationState(): void {
  isMobileViewport.value = window.innerWidth < 768;

  const scroller = navigationScroller.value;
  if (!scroller || isMobileViewport.value) {
    hasNavigationOverflow.value = false;
    canScrollNavigationLeft.value = false;
    canScrollNavigationRight.value = false;
    return;
  }

  const maxScrollLeft = scroller.scrollWidth - scroller.clientWidth;
  hasNavigationOverflow.value = maxScrollLeft > 1;
  canScrollNavigationLeft.value = scroller.scrollLeft > 1;
  canScrollNavigationRight.value = scroller.scrollLeft < maxScrollLeft - 1;
}

function scrollNavigationLeft(): void {
  navigationScroller.value?.scrollBy({
    left: -240,
    behavior: "smooth",
  });
}

function scrollNavigationRight(): void {
  navigationScroller.value?.scrollBy({
    left: 240,
    behavior: "smooth",
  });
}

function observeNavigationScroller(): void {
  if (observedNavigationScroller === navigationScroller.value) return;

  if (observedNavigationScroller) {
    observedNavigationScroller.removeEventListener("scroll", updateNavigationState);
  }
  resizeObserver?.disconnect();
  observedNavigationScroller = navigationScroller.value;

  if (observedNavigationScroller) {
    resizeObserver = new ResizeObserver(updateNavigationState);
    resizeObserver.observe(observedNavigationScroller);
    observedNavigationScroller.addEventListener("scroll", updateNavigationState, { passive: true });
  } else {
    resizeObserver = null;
  }
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
  window.addEventListener("resize", updateNavigationState);
  observeNavigationScroller();

  // Load user data and libraries if authenticated but not yet loaded
  await Promise.all([loadUser(), loadLibraries()]);
  await nextTick();
  observeNavigationScroller();
  updateNavigationState();
});

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside);
  document.removeEventListener("keydown", handleEscape);
  window.removeEventListener("resize", updateNavigationState);
  observedNavigationScroller?.removeEventListener("scroll", updateNavigationState);
  resizeObserver?.disconnect();
});

watch(
  () => [libraries.value.length, isAdmin.value, currentUser.value?.username, currentUser.value?.profile_image_url],
  async () => {
    await nextTick();
    observeNavigationScroller();
    updateNavigationState();
  },
);

watch(navigationScroller, async () => {
  await nextTick();
  observeNavigationScroller();
  updateNavigationState();
});

watch(
  () => route.fullPath,
  () => {
    closeDropdown();
    closeMobileNavigation();
  },
);

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
  <header class="sticky top-0 z-50 border-b border-gray-800 bg-gray-900/95 backdrop-blur-xs">
    <div class="mx-auto flex items-center justify-between gap-4 px-4 py-3 sm:px-6 sm:py-4">
      <div class="flex min-w-0 flex-1 items-center gap-4 lg:gap-6">
        <button
          type="button"
          class="h-10 w-10 items-center justify-center rounded-md text-gray-300 transition-colors hover:bg-gray-800 hover:text-white"
          :class="isMobileViewport ? 'inline-flex' : 'hidden'"
          :aria-label="$t('common.menu')"
          :aria-expanded="isMobileNavigationOpen"
          @click="toggleMobileNavigation"
        >
          <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </button>
        <router-link
          to="/"
          class="shrink-0 text-2xl font-bold text-white transition-colors hover:text-primary-400 sm:text-3xl"
        >
          {{ $t('common.appName') }}
        </router-link>
        <div v-if="!isMobileViewport" class="relative min-w-0 flex-1">
          <nav
            ref="navigationScroller"
            class="ferelix-hide-scrollbar flex min-w-0 max-w-full items-center gap-1 overflow-x-auto px-8"
            :class="hasNavigationOverflow ? 'ferelix-nav-overflow-fade' : ''"
            :aria-label="$t('common.menu')"
          >
            <router-link
              v-for="item in navigationItems"
              :key="item.id"
              :to="item.to"
              class="group max-w-52 shrink-0 truncate px-3 text-sm font-medium transition-colors"
              :class="
                item.active
                  ? 'text-white'
                  : 'text-gray-300 hover:text-white'
              "
            >
              <span
                class="inline-block max-w-full truncate border-b-2 px-1 py-2 transition-colors"
                :class="item.active ? 'border-primary-500' : 'border-transparent group-hover:border-gray-600'"
              >
                {{ item.label }}
              </span>
            </router-link>
          </nav>
          <button
            v-if="canScrollNavigationLeft"
            type="button"
            class="absolute left-0 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-gray-800/95 text-gray-200 shadow-lg ring-1 ring-gray-700 transition-colors hover:bg-gray-700 hover:text-white"
            :aria-label="$t('common.previous')"
            @click="scrollNavigationLeft"
          >
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button
            v-if="canScrollNavigationRight"
            type="button"
            class="absolute right-0 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-gray-800/95 text-gray-200 shadow-lg ring-1 ring-gray-700 transition-colors hover:bg-gray-700 hover:text-white"
            :aria-label="$t('common.next')"
            @click="scrollNavigationRight"
          >
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>

      <div class="flex shrink-0 items-center gap-3">
        <router-link
          v-if="isAdmin && !isMobileViewport"
          to="/dashboard"
          class="group max-w-52 truncate px-3 text-sm font-medium transition-colors"
          :class="
            route.path === '/dashboard' || route.path.startsWith('/dashboard/')
              ? 'text-white'
              : 'text-gray-300 hover:text-white'
          "
        >
          <span
            class="inline-block max-w-full truncate border-b-2 px-1 py-2 transition-colors"
            :class="
              route.path === '/dashboard' || route.path.startsWith('/dashboard/')
                ? 'border-primary-500'
                : 'border-transparent group-hover:border-gray-600'
            "
          >
            {{ $t('common.dashboard') }}
          </span>
        </router-link>
        <div ref="dropdownContainer" class="relative">
          <button
            type="button"
            class="flex h-10 w-10 items-center justify-center overflow-hidden rounded-full bg-gray-700 text-sm font-semibold text-gray-200 transition-colors hover:bg-gray-600 focus:outline-hidden focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 focus:ring-offset-gray-900"
            :aria-expanded="isDropdownOpen"
            :aria-label="$t('common.userMenu')"
            @click="toggleDropdown"
          >
            <img
              v-if="userProfileImageUrl"
              :src="userProfileImageUrl"
              :alt="currentUser?.username || $t('common.user')"
              class="h-full w-full object-cover"
            />
            <span v-else>{{ userInitials }}</span>
          </button>

          <transition
            enter-active-class="transition ease-out duration-100"
            enter-from-class="scale-95 opacity-0"
            enter-to-class="scale-100 opacity-100"
            leave-active-class="transition ease-in duration-75"
            leave-from-class="scale-100 opacity-100"
            leave-to-class="scale-95 opacity-0"
          >
            <div
              v-if="isDropdownOpen"
              class="absolute right-0 mt-2 w-48 rounded-md bg-gray-800 shadow-lg ring-1 ring-black/20 focus:outline-hidden"
            >
              <div class="py-1" role="menu" aria-orientation="vertical">
                <router-link
                  to="/settings"
                  class="block px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
                  role="menuitem"
                >
                  {{ $t('common.settings') }}
                </router-link>
                <button
                  type="button"
                  class="block w-full px-4 py-2 text-left text-sm text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
                  role="menuitem"
                  @click="handleLogout"
                >
                  {{ $t('common.logout') }}
                </button>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </div>
  </header>

  <teleport to="body">
    <transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="isMobileNavigationOpen"
        class="fixed inset-x-0 bottom-0 top-[65px] z-[80] bg-black/60 sm:top-[73px]"
        @click="closeMobileNavigation"
      >
        <nav
          class="relative flex h-full w-72 max-w-[85vw] flex-col bg-gray-950 p-4 shadow-2xl"
          :aria-label="$t('common.menu')"
          @click.stop
        >
          <button
            type="button"
            class="absolute right-4 top-4 rounded-md p-2 text-gray-300 hover:bg-gray-800 hover:text-white"
            :aria-label="$t('common.close')"
            @click="closeMobileNavigation"
          >
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
          <div class="flex min-h-0 flex-1 flex-col">
            <div class="space-y-1">
              <router-link
                v-for="item in navigationItems"
                :key="`mobile-${item.id}`"
                :to="item.to"
                class="group block truncate py-2 text-sm font-medium transition-colors"
                :class="
                  item.active
                    ? 'text-white'
                    : 'text-gray-300 hover:text-white'
                "
              >
                <span
                  class="inline-block max-w-full truncate border-l-2 px-3 transition-colors"
                  :class="item.active ? 'border-primary-500' : 'border-transparent group-hover:border-gray-700'"
                >
                  {{ item.label }}
                </span>
              </router-link>
            </div>
            <router-link
              v-if="isAdmin"
              to="/dashboard"
              class="group mt-auto block py-3 text-sm font-medium transition-colors"
              :class="
                route.path === '/dashboard' || route.path.startsWith('/dashboard/')
                  ? 'text-white'
                  : 'text-gray-300 hover:text-white'
              "
            >
              <span
                class="inline-block max-w-full truncate border-l-2 px-3 transition-colors"
                :class="
                  route.path === '/dashboard' || route.path.startsWith('/dashboard/')
                    ? 'border-primary-500'
                    : 'border-transparent group-hover:border-gray-700'
                "
              >
                {{ $t('common.dashboard') }}
              </span>
            </router-link>
          </div>
        </nav>
      </div>
    </transition>
  </teleport>
</template>
