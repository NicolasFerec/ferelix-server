<script setup lang="ts">
import { computed, onMounted, type Ref, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";
import { type MediaFile, media } from "@/api/client";
import WatchlistButton from "@/components/WatchlistButton.vue";
import { safeReturnTo } from "@/services/authNavigation";
import { getMediaTitleInfo } from "@/services/mediaDisplay";
import PlaybackTrackOptions, { type TrackSelection } from "@/components/PlaybackTrackOptions.vue";
import MenuBar from "../components/MenuBar.vue";

const route = useRoute();
const { t } = useI18n();
const mediaFile: Ref<MediaFile | null> = ref(null);
const loading: Ref<boolean> = ref(false);
const error: Ref<string> = ref("");
const thumbnailFailed = ref(false);
const tracks = ref<TrackSelection>({});
const displayInfo = computed(() =>
  mediaFile.value?.file_name
    ? getMediaTitleInfo(mediaFile.value.file_name)
    : { title: mediaFile.value?.id ? String(mediaFile.value.id) : "", year: null },
);
const resumePosition = computed(() => getResumePosition());
const primaryPlayLabel = computed(() =>
  resumePosition.value > 0 ? t("mediaDetail.resume") : t("mediaDetail.play"),
);
const watchProgressPercent = computed(() => {
  const view = mediaFile.value?.user_view;
  const duration = view?.duration_seconds || mediaFile.value?.duration;
  if (!view || !duration || duration <= 0) return 0;
  if (view.watched) return 100;
  return Math.min(Math.max((view.position_seconds / duration) * 100, 0), 100);
});

async function loadMedia(): Promise<void> {
  loading.value = true;
  error.value = "";

  try {
    mediaFile.value = await media.getMediaFile(Number(route.params.id));
    tracks.value = {};
  } catch (err: unknown) {
    console.error("Failed to load media:", err);
    error.value = t("mediaDetail.loadFailed");
  } finally {
    loading.value = false;
  }
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return t("mediaDetail.duration.hoursMinutes", { hours, minutes });
  }
  return t("mediaDetail.duration.minutes", { minutes });
}

const playbackLocation = computed(() => ({
  name: "player",
  params: { id: String(mediaFile.value?.id) },
  query: tracks.value,
}));
const backLocation = computed(() => route.query.returnTo ? safeReturnTo(route.query.returnTo) : Number(route.query.libraryId) > 0 ? `/library/${Number(route.query.libraryId)}` : "/");

function getResumePosition(): number {
  const view = mediaFile.value?.user_view;
  const duration = view?.duration_seconds || mediaFile.value?.duration;
  if (!view || view.resume_active === false || (view.resume_active === undefined && view.watched) || !duration || duration <= 0) return 0;
  if (view.position_seconds < 10 || view.position_seconds >= duration - 10) return 0;
  return view.position_seconds;
}

function getMediaTitle(): string {
  return displayInfo.value.title;
}

function thumbnailUrl(): string | null {
  if (!mediaFile.value?.id || thumbnailFailed.value) return null;
  return media.getThumbnailUrl(mediaFile.value.id);
}

onMounted(() => {
  loadMedia();
});
</script>

<template>
  <div class="media-detail-view min-h-screen bg-background">
    <MenuBar />
    <div v-if="loading" role="status" class="container mx-auto px-6 py-8 text-center text-gray-400">
      {{ t("mediaDetail.loading") }}
    </div>

    <div v-else-if="error" role="alert" class="container mx-auto px-6 py-8 text-center">
      <p class="text-red-400 mb-4">{{ error }}</p>
      <button
        type="button"
        @click="loadMedia"
        class="px-4 py-2 text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md"
      >
        {{ t("common.retry") }}
      </button>
    </div>

    <main v-else-if="mediaFile" id="main-content" class="relative">
      <!-- Header -->
      <div class="relative h-64 md:h-96 overflow-hidden bg-gray-800">
        <img
          v-if="thumbnailUrl()"
          :src="thumbnailUrl() || undefined"
          alt=""
          width="1280"
          height="720"
          class="absolute inset-0 h-full w-full object-cover opacity-50 blur-sm scale-105"
          @error="thumbnailFailed = true"
        />
        <div
          class="absolute inset-0 bg-linear-to-b from-transparent via-background/50 to-background"
        ></div>

        <!-- Back Button -->
        <RouterLink
          :to="backLocation"
          class="absolute top-4 left-4 z-20 bg-black/50 hover:bg-black/70 backdrop-blur-xs text-white p-2 rounded-full transition-[opacity,background-color] duration-200 flex items-center justify-center"
          :aria-label="t('mediaDetail.back')"
        >
          <svg aria-hidden="true" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 19l-7-7 7-7"
            />
          </svg>
        </RouterLink>
      </div>

      <!-- Content -->
      <div class="container mx-auto px-6 pt-0 pb-8 -mt-56 relative z-10">
        <div class="flex flex-col md:flex-row gap-8">
          <!-- Poster -->
          <div class="shrink-0">
            <RouterLink
              :to="playbackLocation"
              class="group relative flex aspect-2/3 w-48 cursor-pointer items-center justify-center overflow-hidden rounded-lg bg-gray-800 shadow-2xl transition-transform duration-200 hover:scale-[1.01] focus:outline-none focus:ring-2 focus:ring-primary-400 md:w-64"
              :aria-label="t('mediaDetail.play')"

            >
              <img
                v-if="thumbnailUrl()"
                :src="thumbnailUrl() || undefined"
                :alt="getMediaTitle()"
                width="256"
                height="384"
                class="h-full w-full object-cover transition-opacity duration-200 group-hover:opacity-55 group-focus-visible:opacity-55"
                @error="thumbnailFailed = true"
              />
              <svg aria-hidden="true"
                v-else
                class="h-24 w-24 text-gray-600 transition-opacity duration-200 group-hover:opacity-55 group-focus-visible:opacity-55"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                />
              </svg>
              <span
                class="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-[opacity,background-color] duration-200 group-hover:bg-black/45 group-hover:opacity-100 group-focus-visible:bg-black/45 group-focus-visible:opacity-100"
                aria-hidden="true"
              >
                <span class="flex h-16 w-16 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-xs">
                  <svg aria-hidden="true" class="ml-1 h-8 w-8" fill="currentColor" viewBox="0 0 20 20">
                    <path
                      d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"
                    />
                  </svg>
                </span>
              </span>
              <div v-if="watchProgressPercent > 0" class="absolute bottom-0 left-0 right-0 h-1.5 bg-black/60">
                <div class="h-full bg-primary-500" :style="{ width: `${watchProgressPercent}%` }"></div>
              </div>
            </RouterLink>
          </div>

          <!-- Info -->
          <div class="flex-1 text-white">
            <div class="mb-4 flex flex-col items-start justify-between gap-5 lg:flex-row">
              <h1 class="min-w-0 text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-tight">{{ getMediaTitle() }}</h1>
              <RouterLink
                v-if="mediaFile.id"
                :to="playbackLocation"

                class="shrink-0 bg-primary-600 hover:bg-primary-700 text-white font-semibold py-2.5 px-6 rounded-lg transition-colors duration-200 flex items-center gap-2"
              >
                <svg aria-hidden="true" class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"
                  />
                </svg>
                {{ primaryPlayLabel }}
              </RouterLink>
            </div>
            <WatchlistButton class="mb-5" :media-id="mediaFile.id" :in-watchlist="mediaFile.in_watchlist" @updated="mediaFile.in_watchlist = $event" />
            <div class="flex items-center gap-4 mb-6 text-gray-300">
              <span v-if="mediaFile.duration">{{ formatDuration(mediaFile.duration) }}</span>
              <span v-if="mediaFile.duration && displayInfo.year">•</span>
              <span v-if="displayInfo.year">{{ displayInfo.year }}</span>
              <span v-if="mediaFile.user_view?.watched">•</span>
              <span v-if="mediaFile.user_view?.watched">{{ t("mediaDetail.watched") }}</span>
              <span v-else-if="resumePosition > 0">•</span>
              <span v-if="resumePosition > 0">{{ t("mediaDetail.resume") }} {{ formatDuration(resumePosition) }}</span>
            </div>

            <PlaybackTrackOptions :file="mediaFile" v-model="tracks" />
          </div>
        </div>
      </div>
    </main>

    <div v-else class="container mx-auto px-6 py-8 text-center text-white">
      <p class="text-xl">{{ t("mediaDetail.notFound") }}</p>
      <router-link to="/" class="text-primary-400 hover:text-primary-300 mt-4 inline-block">
        {{ t("mediaDetail.backHome") }}
      </router-link>
    </div>
  </div>
</template>
