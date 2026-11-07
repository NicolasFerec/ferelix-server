import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { libraries } from "@/api/client";
import MediaRow from "@/components/MediaRow.vue";
import LibraryView from "@/views/LibraryView.vue";

vi.mock("@/api/client", () => ({
    libraries: { getLibraries: vi.fn(), getLibraryRows: vi.fn(), getLibraryItems: vi.fn() },
}));
let wrapper: VueWrapper | undefined;
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(libraries.getLibraries).mockResolvedValue([{ id: 1, name: "Films" }] as never);
    vi.mocked(libraries.getLibraryRows).mockResolvedValue([]);
    vi.mocked(libraries.getLibraryItems).mockResolvedValue([]);
});
afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
    vi.unstubAllGlobals();
});
async function openLibrary(path: string) {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: "/library/:id", component: LibraryView }],
    });
    await router.push(path);
    wrapper = mount(LibraryView, {
        global: {
            plugins: [router],
            stubs: {
                MenuBar: true,
                MediaRow: true,
                MediaCard: { props: ["mediaFile"], template: "<span>{{ mediaFile.file_name }}</span>" },
            },
        },
    });
    await flushPromises();
    return router;
}
it("does not fetch catalogue cards while showing recommendations", async () => {
    await openLibrary("/library/1");
    expect(libraries.getLibraryRows).toHaveBeenCalledOnce();
    expect(libraries.getLibraryItems).not.toHaveBeenCalled();
});
it("requests 48 cards and one look-ahead for the selected page", async () => {
    vi.mocked(libraries.getLibraryItems).mockResolvedValue(
        Array.from({ length: 49 }, (_, index) => ({ id: index + 49, file_name: `Film ${index + 49}` })) as never,
    );
    await openLibrary("/library/1?tab=library&page=2");
    expect(libraries.getLibraryRows).not.toHaveBeenCalled();
    expect(libraries.getLibraryItems).toHaveBeenCalledWith(1, 48, 49, expect.any(AbortSignal));
    expect(wrapper?.text()).toContain("Film 96");
    expect(wrapper?.text()).not.toContain("Film 97");
    expect(wrapper?.find('a[href*="page=3"]').exists()).toBe(true);
});
it("ignores a stale page response after navigating forward", async () => {
    let complete: (cards: never) => void = () => {};
    vi.mocked(libraries.getLibraryItems).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const router = await openLibrary("/library/1?tab=library&page=2");
    vi.mocked(libraries.getLibraryItems).mockResolvedValue([{ id: 97, file_name: "Current page" }] as never);
    await router.push("/library/1?tab=library&page=3");
    await flushPromises();
    complete([{ id: 49, file_name: "Stale page" }] as never);
    await flushPromises();
    expect(wrapper?.text()).toContain("Current page");
    expect(wrapper?.text()).not.toContain("Stale page");
    expect(vi.mocked(libraries.getLibraryItems).mock.calls[0][3]?.aborted).toBe(true);
});
it("disables row arrows when there is no content left to scroll", async () => {
    let resized = () => {};
    vi.stubGlobal(
        "ResizeObserver",
        class {
            constructor(callback: () => void) {
                resized = callback;
            }
            observe() {}
            disconnect() {}
        },
    );
    wrapper = mount(MediaRow, { props: { displayName: "Films", items: [] }, global: { stubs: { MediaCard: true } } });
    const scroller = wrapper.get(".overflow-x-auto");
    const element = scroller.element;
    Object.defineProperties(element, {
        scrollWidth: { value: 1000, configurable: true },
        clientWidth: { value: 500, configurable: true },
        scrollLeft: { value: 0, writable: true },
    });
    resized();
    await flushPromises();
    const buttons = wrapper.findAll("button");
    expect(buttons.map((button) => button.attributes("disabled") !== undefined)).toEqual([true, false]);
    element.scrollLeft = 500;
    await scroller.trigger("scroll");
    expect(buttons.map((button) => button.attributes("disabled") !== undefined)).toEqual([false, true]);
    Object.defineProperty(element, "scrollWidth", { value: 500 });
    element.scrollLeft = 0;
    resized();
    await flushPromises();
    expect(buttons.map((button) => button.attributes("disabled") !== undefined)).toEqual([true, true]);
});
