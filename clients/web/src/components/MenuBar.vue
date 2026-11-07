<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { auth, getAccessToken, type Library, libraries as libraryApi } from "@/api/client";
import { useUser } from "@/composables/useUser";

const route = useRoute();
const router = useRouter();
const { user, isAdmin, clearUser, loadUser } = useUser();
const libraries = ref<Library[]>([]);
const mobileOpen = ref(false);
const mobileTrigger = ref<HTMLButtonElement | null>(null);
const userMenu = ref<HTMLDetailsElement | null>(null);
const avatar = computed(() => {
  if (!user.value?.profile_image_url) return null;
  const url = new URL(user.value.profile_image_url, window.location.origin);
  const token = getAccessToken();
  if (token) url.searchParams.set("api_key", token);
  return `${url.pathname}${url.search}`;
});
const activeLibrary = computed(() => Number(route.name === "library" ? route.params.id : route.query.libraryId));
function closeMenus(event?: Event) {
  if (!event || event.type === "keydown") {
    if (event instanceof KeyboardEvent && event.key !== "Escape") return;
    if (mobileOpen.value) { mobileOpen.value = false; mobileTrigger.value?.focus(); }
    if (userMenu.value?.open) { userMenu.value.open = false; userMenu.value.querySelector("summary")?.focus(); }
  } else if (userMenu.value && !userMenu.value.contains(event.target as Node)) userMenu.value.open = false;
}
async function logout() {
  await auth.logout();
  clearUser();
  await router.replace("/login");
}
onMounted(() => {
  void loadUser();
  void libraryApi.getLibraries().then(value => { libraries.value = value; }).catch(() => {});
  document.addEventListener("click", closeMenus);
  document.addEventListener("keydown", closeMenus);
});
onUnmounted(() => { document.removeEventListener("click", closeMenus); document.removeEventListener("keydown", closeMenus); });
watch(() => route.fullPath, () => closeMenus());
</script>

<template>
  <header class="sticky top-0 z-50 border-b border-white/5 bg-background/95 backdrop-blur-md">
    <div class="mx-auto flex h-18 max-w-[1600px] items-center gap-5 px-5 sm:px-8 lg:px-12">
      <RouterLink to="/" class="shrink-0 text-2xl font-bold tracking-tight" translate="no">Ferelix<span class="text-primary-400">.</span></RouterLink>
      <nav class="ferelix-hide-scrollbar hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto md:flex" :aria-label="$t('common.menu')">
        <RouterLink to="/" class="shrink-0 rounded-lg px-3 py-2 text-sm transition-colors" :class="route.name === 'home' ? 'bg-white/8 text-white' : 'text-muted hover:text-white'">{{ $t('common.homepage') }}</RouterLink>
        <RouterLink to="/watchlist" class="shrink-0 rounded-lg px-3 py-2 text-sm transition-colors" :class="route.name === 'watchlist' ? 'bg-white/8 text-white' : 'text-muted hover:text-white'">{{ $t('watchlist.title') }}</RouterLink>
        <RouterLink v-for="library in libraries" :key="library.id" :to="`/library/${library.id}`" class="max-w-48 shrink-0 truncate rounded-lg px-3 py-2 text-sm transition-colors" :class="activeLibrary === library.id ? 'bg-white/8 text-white' : 'text-muted hover:text-white'">{{ library.name }}</RouterLink>
      </nav>
      <div class="ml-auto flex shrink-0 items-center gap-3">
        <RouterLink to="/search" class="flex size-10 items-center justify-center rounded-lg text-muted hover:bg-surface hover:text-white" :class="{'bg-white/8 text-white': route.name === 'search'}" :aria-label="$t('discovery.title')" :title="$t('discovery.title')"><svg aria-hidden="true" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg></RouterLink>
        <RouterLink v-if="isAdmin" to="/dashboard" class="hidden rounded-lg px-3 py-2 text-sm text-muted hover:bg-white/5 hover:text-white lg:block">{{ $t('common.dashboard') }}</RouterLink>
        <details ref="userMenu" class="relative">
          <summary class="flex size-10 cursor-pointer list-none items-center justify-center overflow-hidden rounded-full border border-outline bg-surface text-sm font-semibold text-gray-200 hover:border-primary-400 [&::-webkit-details-marker]:hidden" :aria-label="$t('common.userMenu')">
            <img v-if="avatar" :src="avatar" alt="" width="40" height="40" class="size-full object-cover" /><span v-else>{{ user?.username?.slice(0, 2).toUpperCase() || '…' }}</span>
          </summary>
          <div class="absolute right-0 z-70 mt-3 min-w-56 overflow-hidden rounded-xl border border-outline bg-surface p-2 shadow-2xl">
            <p class="truncate border-b border-outline px-3 py-3 text-sm font-semibold">{{ user?.username }}</p>
            <RouterLink to="/settings" class="mt-1 block rounded-lg px-3 py-3 text-sm text-gray-200 hover:bg-white/5">{{ $t('common.settings') }}</RouterLink>
            <RouterLink v-if="isAdmin" to="/dashboard" class="block rounded-lg px-3 py-3 text-sm text-gray-200 hover:bg-white/5 lg:hidden">{{ $t('common.dashboard') }}</RouterLink>
            <button type="button" class="block w-full rounded-lg px-3 py-3 text-left text-sm text-gray-200 hover:bg-white/5" @click="logout">{{ $t('common.logout') }}</button>
          </div>
        </details>
        <button ref="mobileTrigger" type="button" class="flex size-10 items-center justify-center rounded-lg border border-outline text-gray-200 hover:bg-surface md:hidden" :aria-label="$t('common.menu')" :aria-expanded="mobileOpen" aria-controls="mobile-navigation" @click="mobileOpen = !mobileOpen">
          <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24" aria-hidden="true"><path :d="mobileOpen ? 'M6 6l12 12M6 18L18 6' : 'M4 6h16M4 12h16M4 18h16'" /></svg>
        </button>
      </div>
    </div>
    <nav v-if="mobileOpen" id="mobile-navigation" class="max-h-[60dvh] overflow-y-auto border-t border-outline px-5 py-3 md:hidden" :aria-label="$t('common.menu')">
      <RouterLink to="/" class="block rounded-lg px-3 py-3 text-sm hover:bg-surface">{{ $t('common.homepage') }}</RouterLink>
      <RouterLink to="/watchlist" class="block rounded-lg px-3 py-3 text-sm hover:bg-surface" :class="route.name === 'watchlist' ? 'text-primary-300' : 'text-gray-200'">{{ $t('watchlist.title') }}</RouterLink>
      <RouterLink v-for="library in libraries" :key="library.id" :to="`/library/${library.id}`" class="block truncate rounded-lg px-3 py-3 text-sm hover:bg-surface" :class="activeLibrary === library.id ? 'text-primary-300' : 'text-gray-200'">{{ library.name }}</RouterLink>
    </nav>
  </header>
</template>
