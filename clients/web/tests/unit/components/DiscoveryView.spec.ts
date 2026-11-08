import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { items, watchlist } from "@/api/client";
import DiscoveryView from "@/views/DiscoveryView.vue";

vi.mock("@/api/client", () => ({
    media: { getThumbnailUrl: () => "/thumbnail" },
    items: { list: vi.fn(), artworkUrl: () => null },
    watchlist: { list: vi.fn() },
}));
let wrapper: VueWrapper | undefined;
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(items.list).mockResolvedValue([]);
    vi.mocked(watchlist.list).mockResolvedValue([]);
});
afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
    vi.useRealTimers();
});
async function open(path: string) {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [
            { path: "/search", name: "search", component: DiscoveryView },
            { path: "/watchlist", name: "watchlist", component: DiscoveryView },
            { path: "/items/:id", name: "item-detail", component: { template: "<div />" } },
        ],
    });
    await router.push(path);
    const view = mount(DiscoveryView, {
        global: { plugins: [router], stubs: { MenuBar: true, WatchStateMenu: true } },
    });
    wrapper = view;
    await flushPromises();
    return { router, wrapper: view };
}
it("debounces global server search and finds a film outside a loaded library page", async () => {
    vi.useFakeTimers();
    vi.mocked(items.list).mockResolvedValue([{ id: 500, kind: "movie", title: "Matrix.1999.mkv" }] as never);
    const { router, wrapper } = await open("/search");
    expect(items.list).not.toHaveBeenCalled();
    const field = wrapper.get('input[type="search"]');
    await field.setValue("Mat");
    await vi.advanceTimersByTimeAsync(200);
    await field.setValue("Matrix");
    await vi.advanceTimersByTimeAsync(299);
    expect(items.list).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(items.list).toHaveBeenCalledOnce();
    expect(items.list).toHaveBeenCalledWith({ q: "Matrix", skip: 0, limit: 49 }, expect.any(AbortSignal));
    expect(router.currentRoute.value.query.q).toBe("Matrix");
    expect(wrapper.text()).toContain("Matrix");
    const link = wrapper.get('a[href^="/items/500"]');
    expect(link.attributes("href")).toContain("returnTo=/search?q=Matrix");
});
it("preserves query and bounded pagination in the URL", async () => {
    vi.mocked(items.list).mockResolvedValue(
        Array.from({ length: 49 }, (_, index) => ({
            id: 49 + index,
            kind: "movie",
            title: `Result ${49 + index}`,
        })) as never,
    );
    const { router, wrapper } = await open("/search?q=film&page=2");
    expect(items.list).toHaveBeenCalledWith({ q: "film", skip: 48, limit: 49 }, expect.any(AbortSignal));
    expect(wrapper.findAll(".item-card")).toHaveLength(48);
    await wrapper.get('a[href*="page=3"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query).toMatchObject({ q: "film", page: "3" });
    expect(items.list).toHaveBeenLastCalledWith({ q: "film", skip: 96, limit: 49 }, expect.any(AbortSignal));
    router.back();
    await flushPromises();
    expect(router.currentRoute.value.query.page).toBe("2");
});
it("aborts obsolete searches and ignores late responses", async () => {
    vi.useFakeTimers();
    let complete: (cards: never) => void = () => {};
    vi.mocked(items.list).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const { wrapper } = await open("/search?q=old");
    vi.mocked(items.list).mockResolvedValue([{ id: 2, kind: "movie", title: "Current result" }] as never);
    await wrapper.get("input").setValue("current");
    await vi.advanceTimersByTimeAsync(300);
    await flushPromises();
    expect(vi.mocked(items.list).mock.calls[0][1]?.aborted).toBe(true);
    complete([{ id: 1, kind: "movie", title: "Obsolete result" }] as never);
    await flushPromises();
    expect(wrapper.text()).toContain("Current result");
    expect(wrapper.text()).not.toContain("Obsolete result");
});
it("keeps the current request usable when typing and restoring the same query", async () => {
    vi.useFakeTimers();
    let complete: (cards: never) => void = () => {};
    vi.mocked(items.list).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const { wrapper } = await open("/search?q=film");
    await wrapper.get("input").setValue("films");
    await wrapper.get("input").setValue("film");
    complete([{ id: 1, kind: "movie", title: "Restored result" }] as never);
    await flushPromises();
    expect(wrapper.text()).toContain("Restored result");
    expect(items.list).toHaveBeenCalledOnce();
});
it("offers retry after a search error", async () => {
    vi.mocked(items.list).mockRejectedValueOnce(new Error("Unavailable"));
    const { wrapper } = await open("/search?q=film");
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    await wrapper.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(items.list).toHaveBeenCalledTimes(2);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
});
it("loads a personal list page without searching the catalogue", async () => {
    const { wrapper } = await open("/watchlist?page=2");
    expect(watchlist.list).toHaveBeenCalledWith(48, 49, expect.any(AbortSignal));
    expect(items.list).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("watchlist.empty");
});
