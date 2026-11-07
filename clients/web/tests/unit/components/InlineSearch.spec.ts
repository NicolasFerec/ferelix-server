import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { media } from "@/api/client";
import InlineSearch from "@/components/InlineSearch.vue";

vi.mock("@/api/client", () => ({ media: { search: vi.fn(), getThumbnailUrl: () => "/thumbnail" } }));
let wrapper: VueWrapper | undefined;
beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    vi.mocked(media.search).mockResolvedValue([]);
});
afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
    vi.useRealTimers();
});
async function open() {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [
            { path: "/", name: "home", component: { template: "<div/>" } },
            { path: "/search", name: "search", component: { template: "<div/>" } },
            { path: "/media/:id", name: "media-detail", component: { template: "<div/>" } },
        ],
    });
    await router.push("/");
    const view = mount(InlineSearch, { attachTo: document.body, global: { plugins: [router] } });
    wrapper = view;
    await view.get("button").trigger("click");
    return { view, router };
}
it("opens in place and only requests five suggestions after typing settles", async () => {
    const { view, router } = await open();
    expect(document.activeElement).toBe(view.get("input").element);
    expect(media.search).not.toHaveBeenCalled();
    await view.get("input").setValue("Mat");
    await vi.advanceTimersByTimeAsync(100);
    await view.get("input").setValue("Matrix");
    await vi.advanceTimersByTimeAsync(250);
    expect(media.search).toHaveBeenCalledExactlyOnceWith("Matrix", 0, 5, expect.any(AbortSignal));
    expect(router.currentRoute.value.path).toBe("/");
});
it("submits the trimmed query to the full search page without waiting for suggestions", async () => {
    const { view, router } = await open();
    await view.get("input").setValue(" Matrix ");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/search?q=Matrix");
    expect(view.find("input").exists()).toBe(false);
    await vi.advanceTimersByTimeAsync(250);
    expect(media.search).not.toHaveBeenCalled();
});
it("opens all results from the link and closes the preview", async () => {
    const { view, router } = await open();
    await view.get("input").setValue("Matrix");
    await view.get("[data-search-all]").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/search?q=Matrix");
    expect(view.find("input").exists()).toBe(false);
});
it("ignores late responses and clears stale suggestions as soon as the query changes", async () => {
    let finish: (value: never) => void = () => {};
    vi.mocked(media.search).mockReturnValueOnce(
        new Promise((resolve) => {
            finish = resolve;
        }),
    );
    const { view } = await open();
    await view.get("input").setValue("old");
    await vi.advanceTimersByTimeAsync(250);
    const signal = vi.mocked(media.search).mock.calls[0][3];
    vi.mocked(media.search).mockResolvedValue([{ id: 2, file_name: "Current.mkv" }] as never);
    await view.get("input").setValue("current");
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(250);
    finish([{ id: 1, file_name: "Obsolete.mkv" }] as never);
    await flushPromises();
    expect(view.text()).toContain("Current");
    expect(view.text()).not.toContain("Obsolete");
    await view.get("input").setValue("new");
    expect(view.find("[data-search-result]").exists()).toBe(false);
});
it("supports arrow navigation, Escape focus restoration and cancels work on close", async () => {
    vi.mocked(media.search).mockResolvedValue([{ id: 2, file_name: "Matrix.mkv" }] as never);
    const { view } = await open();
    await view.get("input").setValue("matrix");
    await vi.advanceTimersByTimeAsync(250);
    await view.get("input").trigger("keydown", { key: "ArrowDown" });
    expect(document.activeElement).toBe(view.get("[data-search-result]").element);
    await view.get("[data-search-result]").trigger("keydown", { key: "Escape" });
    expect(view.find("input").exists()).toBe(false);
    expect(document.activeElement).toBe(view.get("button").element);
    expect(vi.mocked(media.search).mock.calls[0][3]?.aborted).toBe(true);
});
it("shows an error and lets the user retry without leaving the page", async () => {
    vi.mocked(media.search).mockRejectedValueOnce(new Error("Offline"));
    const { view, router } = await open();
    await view.get("input").setValue("matrix");
    await vi.advanceTimersByTimeAsync(250);
    expect(view.find('[role="alert"]').exists()).toBe(true);
    await view.get('[role="alert"] button').trigger("click");
    await vi.advanceTimersByTimeAsync(250);
    expect(media.search).toHaveBeenCalledTimes(2);
    expect(view.find('[role="alert"]').exists()).toBe(false);
    expect(router.currentRoute.value.path).toBe("/");
});
