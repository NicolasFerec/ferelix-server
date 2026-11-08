import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { items, media } from "@/api/client";
import DropdownSelect from "@/components/DropdownSelect.vue";
import ItemDetailView from "@/views/ItemDetailView.vue";

vi.mock("@/api/client", () => ({
    media: { getMediaFile: vi.fn() },
    items: { get: vi.fn(), list: vi.fn(), continuation: vi.fn(), artworkUrl: () => null },
}));
const access = vi.hoisted(() => ({ admin: false }));
vi.mock("@/composables/useUser", () => ({ useUser: () => ({ isAdmin: access.admin }) }));
let wrapper: VueWrapper | undefined;
const series = {
    id: 1,
    kind: "series",
    title: "Full series",
    genres: [],
    credits: [],
    hierarchy_complete: true,
    state_revision: 0,
    watched: false,
};
beforeEach(() => {
    vi.resetAllMocks();
    access.admin = false;
    vi.mocked(items.get).mockResolvedValue(series as never);
    vi.mocked(items.list).mockImplementation(async (options) =>
        options.kind === "season" ? ([{ id: 10, kind: "season", title: "Season one", season_number: 1 }] as never) : [],
    );
    vi.mocked(items.continuation).mockResolvedValue({
        status: "missing",
        item: { id: 12, title: "Missing second episode" },
        media_file_id: null,
        position_seconds: 0,
    } as never);
});
afterEach(() => wrapper?.unmount());
async function open(path = "/items/1") {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [
            { path: "/items/:id", name: "item-detail", component: ItemDetailView },
            { path: "/player/:id", name: "player", component: { template: "<div/>" } },
            { path: "/media/:id", name: "media-detail", component: { template: "<div/>" } },
        ],
    });
    await router.push(path);
    const view = mount(ItemDetailView, {
        global: {
            plugins: [router],
            stubs: {
                MenuBar: true,
                MetadataEditor: {
                    emits: ["saved", "close"],
                    template: `<button class="editor-save" @click="$emit('saved')">Save editor</button>`,
                },
                WatchStateMenu: true,
                WatchlistButton: true,
                ItemCardView: { props: ["item"], template: "<p>{{ item.title }} {{ item.availability }}</p>" },
            },
        },
    });
    wrapper = view;
    await flushPromises();
    return { view, router };
}
it("shows missing episodes and refuses to skip an unavailable immediate continuation", async () => {
    vi.mocked(items.list).mockImplementation(async (options) =>
        options.kind === "season"
            ? ([{ id: 10, kind: "season", title: "Season one", season_number: 1 }] as never)
            : ([
                  { id: 11, title: "First episode", availability: "available" },
                  { id: 12, title: "Missing second episode", availability: "missing" },
              ] as never),
    );
    const { view } = await open();
    expect(view.text()).toContain("Missing second episode");
    expect(view.text()).toContain("items.continuation.missing");
    expect(view.find('a[href^="/player/"]').exists()).toBe(false);
    expect(items.list).toHaveBeenCalledWith(
        { parent_id: 10, kind: "episode", skip: 0, limit: 49 },
        expect.any(AbortSignal),
    );
});
it("paginates episodes without requiring the complete series in memory", async () => {
    vi.mocked(items.list).mockImplementation(async (options) =>
        options.kind === "season"
            ? ([{ id: 10, kind: "season", title: "Season one", season_number: 1 }] as never)
            : (Array.from({ length: 49 }, (_, i) => ({
                  id: i + 49,
                  title: `Episode ${i + 49}`,
                  availability: "available",
              })) as never),
    );
    const { view } = await open("/items/1?page=2");
    expect(view.text()).toContain("Episode 96");
    expect(view.text()).not.toContain("Episode 97");
    expect(view.find('a[href*="page=3"]').exists()).toBe(true);
    expect(items.list).toHaveBeenCalledWith(
        { parent_id: 10, kind: "episode", skip: 48, limit: 49 },
        expect.any(AbortSignal),
    );
});
it("ignores late season results when navigating to another series", async () => {
    let complete: (value: never) => void = () => {};
    vi.mocked(items.list).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const { view, router } = await open();
    vi.mocked(items.get).mockResolvedValue({ ...series, id: 2, title: "New series" } as never);
    await router.push("/items/2");
    await flushPromises();
    complete([{ id: 99, kind: "season", title: "Obsolete season", season_number: 1 }] as never);
    await flushPromises();
    expect(view.text()).toContain("New series");
    expect(view.text()).not.toContain("Obsolete season");
});
it("uses the physical continuation position in the play link", async () => {
    vi.mocked(items.continuation).mockResolvedValue({
        status: "ready",
        item: { id: 12, playable_file_id: 22, resume_active: true },
        media_file_id: 22,
        position_seconds: 1260,
    } as never);
    const { view } = await open();
    const href = view.get('a[href^="/player/22"]').attributes("href");
    expect(href).toContain("item=12");
    expect(href).toContain("position=1260");
});

it("keeps the editor mounted while refreshing the detail after a save", async () => {
    access.admin = true;
    const { view } = await open();
    const edit = view.findAll("button").find((button) => button.text() === "metadata.edit");
    if (!edit) throw new Error("Editor button missing");
    await edit.trigger("click");
    await flushPromises();
    vi.mocked(items.get).mockReturnValue(new Promise(() => {}));
    await view.get(".editor-save").trigger("click");
    await flushPromises();
    expect(view.find(".editor-save").exists()).toBe(true);
    expect(view.text()).toContain("Full series");
});
it("restores the default season when browser history removes the season query", async () => {
    vi.mocked(items.list).mockImplementation(async (options) =>
        options.kind === "season"
            ? ([
                  { id: 10, kind: "season", title: "Season one", season_number: 1 },
                  { id: 20, kind: "season", title: "Season two", season_number: 2 },
              ] as never)
            : [],
    );
    const { router } = await open();
    await router.push("/items/1?season=20");
    await flushPromises();
    expect(items.list).toHaveBeenLastCalledWith(
        { parent_id: 20, kind: "episode", skip: 0, limit: 49 },
        expect.any(AbortSignal),
    );
    router.back();
    await flushPromises();
    expect(items.list).toHaveBeenLastCalledWith(
        { parent_id: 10, kind: "episode", skip: 0, limit: 49 },
        expect.any(AbortSignal),
    );
    expect(items.get).toHaveBeenCalledTimes(1);
    expect(vi.mocked(items.list).mock.calls.filter(([options]) => options.kind === "season")).toHaveLength(1);
});

it("loads playback options on demand and launches the chosen file with the selected tracks", async () => {
    vi.mocked(items.get).mockResolvedValue({
        ...series, id: 1, kind: "movie", availability: "available", playable_file_id: 42, position_seconds: 120,
    } as never);
    vi.mocked(media.getMediaFile).mockResolvedValue({
        id: 42,
        audio_tracks: [{ stream_index: 2, codec: "aac" }],
        subtitle_tracks: [{ stream_index: 3, codec: "subrip" }],
    } as never);
    const { view } = await open();
    expect(media.getMediaFile).not.toHaveBeenCalled();
    const details = view.get<HTMLDetailsElement>("details");
    details.element.open = true;
    await details.trigger("toggle");
    await flushPromises();
    expect(media.getMediaFile).toHaveBeenCalledWith(42, expect.any(AbortSignal));
    const controls = view.findAllComponents(DropdownSelect);
    controls[1].vm.$emit("update:modelValue", 2);
    await flushPromises();
    controls[2].vm.$emit("update:modelValue", -1);
    await flushPromises();
    const href = view.get('a[href^="/player/42"]').attributes("href");
    const query = new URL(href, "http://localhost").searchParams;
    expect(Object.fromEntries(query)).toMatchObject({ item: "1", position: "120", audio: "2", subtitle: "-1" });
});
