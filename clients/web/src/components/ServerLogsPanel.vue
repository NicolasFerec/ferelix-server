<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { type LogLine, serverLogs } from "@/api/client";
import { useFloatingDropdown } from "@/composables/useFloatingDropdown";
import { useToast } from "@/composables/useToast";

const { t } = useI18n();
const toast = useToast();

const lines = ref<LogLine[]>([]);
const loading = ref(false);
const autoscroll = ref(true);
const logPath = ref("");
const nextOffset = ref(0);
const searchQuery = ref("");
const selectedRange = ref<"500" | "2000" | "10000" | "all">("2000");
const levelOptions = ref(["INFO", "WARNING", "ERROR", "CRITICAL"]);
const channelOptions = ["web", "api", "auth", "scheduler", "scanner", "transcode", "database", "server"];
const selectedLevels = ref<string[]>(["INFO", "WARNING", "ERROR", "CRITICAL"]);
const selectedChannels = ref<string[]>([...channelOptions]);
const logViewport = ref<HTMLElement | null>(null);
let followTimer: number | undefined;

const {
  isOpen: isLevelDropdownOpen,
  triggerRef: levelTriggerRef,
  menuRef: levelMenuRef,
  menuStyle: levelMenuStyle,
  toggle: toggleLevelDropdown,
  close: closeLevelDropdown,
  onTriggerKeydown: onLevelTriggerKeydown,
} = useFloatingDropdown();
const {
  isOpen: isChannelDropdownOpen,
  triggerRef: channelTriggerRef,
  menuRef: channelMenuRef,
  menuStyle: channelMenuStyle,
  toggle: toggleChannelDropdown,
  close: closeChannelDropdown,
  onTriggerKeydown: onChannelTriggerKeydown,
} = useFloatingDropdown();

const rangeOptions = computed(() => [
  { value: "500", label: t("logs.ranges.last500") },
  { value: "2000", label: t("logs.ranges.last2000") },
  { value: "10000", label: t("logs.ranges.last10000") },
  { value: "all", label: t("logs.ranges.all") },
] as const);

const activeLevels = computed(() => {
  if (selectedLevels.value.length === levelOptions.value.length) return undefined;
  if (selectedLevels.value.length === 0) return ["__none__"];
  return selectedLevels.value;
});
const activeChannels = computed(() => {
  if (selectedChannels.value.length === channelOptions.length) return undefined;
  if (selectedChannels.value.length === 0) return ["__none__"];
  return selectedChannels.value;
});
const levelSummary = computed(() => {
  if (selectedLevels.value.length === levelOptions.value.length) return t("logs.allLevels");
  if (selectedLevels.value.length === 0) return t("logs.noLevels");
  return selectedLevels.value.join(", ");
});
const channelSummary = computed(() => {
  if (selectedChannels.value.length === channelOptions.length) return t("logs.allChannels");
  if (selectedChannels.value.length === 0) return t("logs.noChannels");
  return selectedChannels.value.map((channel) => t(`logs.channelNames.${channel}`)).join(", ");
});
const areAllLevelsSelected = computed(() => selectedLevels.value.length === levelOptions.value.length);
const areAllChannelsSelected = computed(() => selectedChannels.value.length === channelOptions.length);
const searchTerms = computed(() => normalizeSearchTerms(searchQuery.value));
const displayedLines = computed(() => {
  if (searchTerms.value.length === 0) return lines.value;
  return lines.value.filter((line) => lineMatchesSearch(line, searchTerms.value));
});

async function loadLogs(): Promise<void> {
  loading.value = true;
  try {
    const response = await serverLogs.getLogs({
      maxLines: selectedRange.value === "all" ? 1000 : Number(selectedRange.value),
      allLines: selectedRange.value === "all",
      levels: activeLevels.value,
      channels: activeChannels.value,
    });
    lines.value = response.lines;
    logPath.value = response.path;
    nextOffset.value = response.next_offset;
    await maybeScrollToBottom();
  } catch (err) {
    console.error("Failed to load server logs:", err);
    toast.error(t("logs.loadFailed"));
  } finally {
    loading.value = false;
  }
}

async function loadLogConfig(): Promise<void> {
  try {
    const config = await serverLogs.getConfig();
    levelOptions.value = config.levels.length > 0 ? config.levels : ["INFO", "WARNING", "ERROR", "CRITICAL"];
    selectedLevels.value = selectedLevels.value.filter((level) => levelOptions.value.includes(level));
    if (selectedLevels.value.length === 0) {
      selectedLevels.value = [...levelOptions.value];
    }
  } catch (err) {
    console.error("Failed to load server log configuration:", err);
  }
}

async function pollTail(): Promise<void> {
  if (loading.value) return;

  try {
    const response = await serverLogs.tail(nextOffset.value, {
      levels: activeLevels.value,
      channels: activeChannels.value,
    });
    nextOffset.value = response.next_offset;
    logPath.value = response.path;
    if (response.lines.length > 0) {
      const previousNumber = lines.value.at(-1)?.number ?? 0;
      const newLines = response.lines.map((line, index) => ({
        ...line,
        number: previousNumber + index + 1,
      }));
      lines.value = [...lines.value, ...newLines].slice(-10000);
      await maybeScrollToBottom();
    }
  } catch (err) {
    console.error("Failed to tail server logs:", err);
  }
}

function setAutoscroll(enabled: boolean): void {
  autoscroll.value = enabled;
  if (autoscroll.value) {
    scrollToBottom();
  }
}

function toggleLevel(level: string): void {
  if (selectedLevels.value.includes(level)) {
    selectedLevels.value = selectedLevels.value.filter((item) => item !== level);
  } else {
    selectedLevels.value = [...selectedLevels.value, level];
  }
  loadLogs();
}

function selectAllLevels(): void {
  selectedLevels.value = [...levelOptions.value];
  loadLogs();
}

function clearLevels(): void {
  selectedLevels.value = [];
  loadLogs();
}

function toggleAllLevels(): void {
  if (areAllLevelsSelected.value) {
    clearLevels();
    return;
  }
  selectAllLevels();
}

function toggleChannel(channel: string): void {
  if (selectedChannels.value.includes(channel)) {
    selectedChannels.value = selectedChannels.value.filter((item) => item !== channel);
  } else {
    selectedChannels.value = [...selectedChannels.value, channel];
  }
  loadLogs();
}

function selectAllChannels(): void {
  selectedChannels.value = [...channelOptions];
  loadLogs();
}

function clearChannels(): void {
  selectedChannels.value = [];
  loadLogs();
}

function toggleAllChannels(): void {
  if (areAllChannelsSelected.value) {
    clearChannels();
    return;
  }
  selectAllChannels();
}

function levelClass(level: string | null | undefined): string {
  switch (level) {
    case "ERROR":
    case "CRITICAL":
      return "text-red-300";
    case "WARNING":
      return "text-yellow-300";
    case "INFO":
      return "text-blue-200";
    case "DEBUG":
      return "text-gray-400";
    default:
      return "text-gray-300";
  }
}

function logMessage(line: LogLine): string {
  if ("message" in line && typeof line.message === "string") {
    return line.message;
  }
  return line.text;
}

function normalizeSearchTerms(query: string): string[] {
  return query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

function searchableText(line: LogLine): string {
  return [formatLogTimestamp(line.timestamp), line.timestamp, line.channel, line.level, logMessage(line)].filter(Boolean).join(" ").toLowerCase();
}

function lineMatchesSearch(line: LogLine, terms: string[]): boolean {
  const text = searchableText(line);
  return terms.every((term) => text.includes(term) || fuzzyPositions(text, term).length > 0);
}

function fuzzyPositions(text: string, term: string): number[] {
  if (!term) return [];

  const positions: number[] = [];
  let cursor = 0;
  for (const char of term) {
    const foundAt = text.indexOf(char, cursor);
    if (foundAt === -1) return [];
    positions.push(foundAt);
    cursor = foundAt + 1;
  }
  return positions;
}

function highlightedSegments(value: string | null | undefined) {
  const text = value || "-";
  const terms = searchTerms.value;
  if (terms.length === 0) return [{ text, highlighted: false }];

  const lowerText = text.toLowerCase();
  const ranges: Array<[number, number]> = [];
  for (const term of terms) {
    let index = lowerText.indexOf(term);
    while (index !== -1) {
      ranges.push([index, index + term.length]);
      index = lowerText.indexOf(term, index + Math.max(term.length, 1));
    }

    if (!lowerText.includes(term)) {
      for (const position of fuzzyPositions(lowerText, term)) {
        ranges.push([position, position + 1]);
      }
    }
  }

  return buildHighlightedSegments(text, ranges);
}

function buildHighlightedSegments(text: string, ranges: Array<[number, number]>) {
  if (ranges.length === 0) return [{ text, highlighted: false }];

  const mergedRanges: Array<[number, number]> = [];
  for (const [start, end] of ranges.sort((a, b) => a[0] - b[0])) {
    const previous = mergedRanges.at(-1);
    if (previous && start <= previous[1]) {
      previous[1] = Math.max(previous[1], end);
    } else {
      mergedRanges.push([start, end]);
    }
  }

  const segments: Array<{ text: string; highlighted: boolean }> = [];
  let cursor = 0;
  for (const [start, end] of mergedRanges) {
    if (start > cursor) {
      segments.push({ text: text.slice(cursor, start), highlighted: false });
    }
    segments.push({ text: text.slice(start, end), highlighted: true });
    cursor = end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), highlighted: false });
  }
  return segments;
}

function formatLogTimestamp(timestamp: string | null | undefined): string {
  if (!timestamp) return "-";
  if (!timestamp.includes("T")) return timestamp;

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (logViewport.value) {
    logViewport.value.scrollTop = logViewport.value.scrollHeight;
  }
}

async function maybeScrollToBottom(): Promise<void> {
  if (autoscroll.value) {
    await scrollToBottom();
  }
}

onMounted(() => {
  loadLogConfig().then(loadLogs);
  followTimer = window.setInterval(pollTail, 2000);
});

onBeforeUnmount(() => {
  if (followTimer) {
    window.clearInterval(followTimer);
  }
});
</script>

<template>
  <div class="server-logs-panel flex h-full min-h-[calc(100vh-137px)] flex-col">
    <div class="mb-4 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold text-white">{{ $t("logs.title") }}</h2>
        <p class="mt-1 text-sm text-gray-400">{{ $t("logs.subtitle") }}</p>
        <p v-if="logPath" class="mt-2 font-mono text-xs text-gray-500">{{ logPath }}</p>
      </div>
      <label class="relative w-full sm:w-80">
        <span class="sr-only">{{ $t("logs.search") }}</span>
        <svg
          class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="m21 21-4.35-4.35m1.1-5.4a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z"
          />
        </svg>
        <input
          v-model="searchQuery"
          type="search"
          class="w-full rounded-md border border-gray-600 bg-gray-800 py-2 pl-9 pr-3 text-sm text-white placeholder:text-gray-500 focus:border-primary-500 focus:outline-none"
          :placeholder="$t('logs.search')"
        />
      </label>
    </div>

    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div>
        <select
          v-model="selectedRange"
          class="rounded-md border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white focus:border-primary-500 focus:outline-none"
          @change="loadLogs"
        >
          <option v-for="option in rangeOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div>
        <button
          ref="levelTriggerRef"
          type="button"
          class="flex min-w-56 cursor-pointer list-none items-center justify-between gap-3 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white hover:border-gray-600"
          :aria-expanded="isLevelDropdownOpen"
          @click="toggleLevelDropdown"
          @keydown="onLevelTriggerKeydown"
        >
          <span class="truncate">
            <span class="mr-2 text-xs font-semibold uppercase text-gray-500">{{ $t("logs.levels") }}</span>
            {{ levelSummary }}
          </span>
          <span
            class="text-gray-500 transition-transform"
            :class="{ 'rotate-180': isLevelDropdownOpen }"
          >⌄</span>
        </button>
        <Teleport to="body">
          <div
            v-if="isLevelDropdownOpen"
            ref="levelMenuRef"
            class="fixed z-[1000] w-64 overflow-x-hidden overflow-y-auto rounded-md border border-gray-700 bg-gray-800 p-2 shadow-xl"
            :style="levelMenuStyle"
            @keydown.esc.stop.prevent="closeLevelDropdown"
          >
            <div class="mb-2 border-b border-gray-700 pb-2">
              <button
                type="button"
                class="rounded px-2 py-1 text-xs font-medium text-primary-200 hover:bg-gray-700 hover:text-white"
                @click="toggleAllLevels"
              >
                {{ areAllLevelsSelected ? $t("logs.clearAll") : $t("logs.selectAll") }}
              </button>
            </div>
            <label
              v-for="level in levelOptions"
              :key="level"
              class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-gray-200 hover:bg-gray-700"
            >
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-gray-600 bg-gray-900 text-primary-600 focus:ring-primary-500"
                :checked="selectedLevels.includes(level)"
                @change="toggleLevel(level)"
              />
              <span>{{ level }}</span>
            </label>
          </div>
        </Teleport>
      </div>

      <div>
        <button
          ref="channelTriggerRef"
          type="button"
          class="flex min-w-64 cursor-pointer list-none items-center justify-between gap-3 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white hover:border-gray-600"
          :aria-expanded="isChannelDropdownOpen"
          @click="toggleChannelDropdown"
          @keydown="onChannelTriggerKeydown"
        >
          <span class="truncate">
            <span class="mr-2 text-xs font-semibold uppercase text-gray-500">{{ $t("logs.channels") }}</span>
            {{ channelSummary }}
          </span>
          <span
            class="text-gray-500 transition-transform"
            :class="{ 'rotate-180': isChannelDropdownOpen }"
          >⌄</span>
        </button>
        <Teleport to="body">
          <div
            v-if="isChannelDropdownOpen"
            ref="channelMenuRef"
            class="fixed z-[1000] w-72 overflow-x-hidden overflow-y-auto rounded-md border border-gray-700 bg-gray-800 p-2 shadow-xl"
            :style="channelMenuStyle"
            @keydown.esc.stop.prevent="closeChannelDropdown"
          >
            <div class="mb-2 border-b border-gray-700 pb-2">
              <button
                type="button"
                class="rounded px-2 py-1 text-xs font-medium text-primary-200 hover:bg-gray-700 hover:text-white"
                @click="toggleAllChannels"
              >
                {{ areAllChannelsSelected ? $t("logs.clearAll") : $t("logs.selectAll") }}
              </button>
            </div>
            <label
              v-for="channel in channelOptions"
              :key="channel"
              class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-gray-200 hover:bg-gray-700"
            >
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-gray-600 bg-gray-900 text-primary-600 focus:ring-primary-500"
                :checked="selectedChannels.includes(channel)"
                @change="toggleChannel(channel)"
              />
              <span>{{ $t(`logs.channelNames.${channel}`) }}</span>
            </label>
          </div>
        </Teleport>
      </div>
    </div>

    <div
      ref="logViewport"
      class="min-h-0 flex-1 overflow-auto rounded-md border border-gray-700 bg-black px-4 py-3 font-mono text-xs leading-5 text-gray-200"
    >
      <div v-if="lines.length === 0" class="py-12 text-center font-sans text-sm text-gray-500">
        {{ loading ? $t("common.loading") : $t("logs.empty") }}
      </div>
      <div v-else-if="displayedLines.length === 0" class="py-12 text-center font-sans text-sm text-gray-500">
        {{ $t("logs.searchNoResults") }}
      </div>
      <div
        v-for="line in displayedLines"
        :key="`${line.number}-${line.text}`"
        class="grid grid-cols-[4rem_11rem_6rem_5rem_minmax(0,1fr)] gap-3 whitespace-pre-wrap"
      >
        <span class="select-none text-right text-gray-600">{{ line.number }}</span>
        <span class="select-none text-gray-500">
          <template v-for="(segment, index) in highlightedSegments(formatLogTimestamp(line.timestamp))" :key="`ts-${line.number}-${index}`">
            <mark v-if="segment.highlighted" class="rounded bg-yellow-300 px-0.5 text-gray-950">{{ segment.text }}</mark>
            <template v-else>{{ segment.text }}</template>
          </template>
        </span>
        <span class="select-none text-gray-500">
          <template v-for="(segment, index) in highlightedSegments(line.channel || 'server')" :key="`ch-${line.number}-${index}`">
            <mark v-if="segment.highlighted" class="rounded bg-yellow-300 px-0.5 text-gray-950">{{ segment.text }}</mark>
            <template v-else>{{ segment.text }}</template>
          </template>
        </span>
        <span class="select-none" :class="levelClass(line.level)">
          <template v-for="(segment, index) in highlightedSegments(line.level)" :key="`lv-${line.number}-${index}`">
            <mark v-if="segment.highlighted" class="rounded bg-yellow-300 px-0.5 text-gray-950">{{ segment.text }}</mark>
            <template v-else>{{ segment.text }}</template>
          </template>
        </span>
        <span :class="levelClass(line.level)">
          <template v-for="(segment, index) in highlightedSegments(logMessage(line))" :key="`msg-${line.number}-${index}`">
            <mark v-if="segment.highlighted" class="rounded bg-yellow-300 px-0.5 text-gray-950">{{ segment.text }}</mark>
            <template v-else>{{ segment.text }}</template>
          </template>
        </span>
      </div>
    </div>

    <label class="mt-2 flex w-max items-center gap-2 text-sm text-gray-400">
      <input
        type="checkbox"
        class="h-4 w-4 rounded border-gray-600 bg-gray-900 text-primary-600 focus:ring-primary-500"
        :checked="autoscroll"
        @change="setAutoscroll(($event.target as HTMLInputElement).checked)"
      />
      <span>{{ $t("logs.autoscroll") }}</span>
    </label>
  </div>
</template>
