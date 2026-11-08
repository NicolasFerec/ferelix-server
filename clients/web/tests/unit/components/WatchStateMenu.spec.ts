import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { items } from "@/api/client";
import WatchStateMenu from "@/components/WatchStateMenu.vue";

vi.mock("@/api/client", () => ({ items: { setWatched: vi.fn(), bulkWatched: vi.fn(), get: vi.fn() } }));
let wrapper: VueWrapper | undefined;
beforeEach(() => vi.resetAllMocks());
afterEach(() => wrapper?.unmount());
function open(kind: "episode" | "series" = "episode") {
    const view = mount(WatchStateMenu, {
        props: { itemId: 7, kind, watched: false, stateRevision: 3 },
        global: { stubs: { Teleport: true, ModalDialog: { template: '<div role="dialog"><slot /></div>' } } },
    });
    wrapper = view;
    return view;
}
it("only displays the confirmed watched state after a successful revision update", async () => {
    let finish: (value: never) => void = () => {};
    vi.mocked(items.setWatched).mockReturnValue(
        new Promise((resolve) => {
            finish = resolve;
        }),
    );
    const view = open();
    await view.get(".watch-state-trigger").trigger("click");
    await view.get(".watch-state-action").trigger("click");
    expect(items.setWatched).toHaveBeenCalledWith(7, true, 3);
    expect(view.get(".watch-state-trigger").attributes("title")).toBe("items.markWatched");
    finish({ watched: true, state_revision: 4 } as never);
    await flushPromises();
    expect(view.get(".watch-state-trigger").attributes("title")).toBe("items.markUnwatched");
    expect(view.emitted("changed")).toHaveLength(1);
});
it("loads a conflicting current revision before the user retries", async () => {
    vi.mocked(items.setWatched).mockRejectedValueOnce(Object.assign(new Error("changed"), { status: 409 }));
    vi.mocked(items.get).mockResolvedValue({ watched: true, state_revision: 5 } as never);
    const view = open();
    await view.get(".watch-state-trigger").trigger("click");
    await view.get(".watch-state-action").trigger("click");
    await flushPromises();
    expect(view.get('[role="alert"]').text()).toContain("items.stateConflict");
    expect(view.emitted("changed")).toBeUndefined();
    vi.mocked(items.setWatched).mockResolvedValue({ watched: false, state_revision: 6 } as never);
    await view.get(".watch-state-trigger").trigger("click");
    await view.get(".watch-state-action").trigger("click");
    await flushPromises();
    expect(items.setWatched).toHaveBeenLastCalledWith(7, false, 5);
});
it("previews a container and requires the exact snapshot token to confirm", async () => {
    vi.mocked(items.bulkWatched)
        .mockResolvedValueOnce({ count: 24, revision_token: "snapshot-A", applied: false } as never)
        .mockResolvedValueOnce({ count: 24, revision_token: "snapshot-A", applied: true } as never);
    const view = open("series");
    await view.get(".watch-state-trigger").trigger("click");
    await view.get(".watch-state-action").trigger("click");
    await flushPromises();
    expect(items.bulkWatched).toHaveBeenCalledOnce();
    expect(items.bulkWatched).toHaveBeenCalledWith(7, true);
    await view.get('[role="dialog"] .button-primary').trigger("click");
    await flushPromises();
    expect(items.bulkWatched).toHaveBeenLastCalledWith(7, true, "snapshot-A");
    expect(view.find('[role="dialog"]').exists()).toBe(false);
});
it("discards a stale bulk preview and never reports unconfirmed changes", async () => {
    vi.mocked(items.bulkWatched)
        .mockResolvedValueOnce({ count: 24, revision_token: "old" } as never)
        .mockRejectedValueOnce(Object.assign(new Error("changed"), { status: 409 }));
    const view = open("series");
    await view.get(".watch-state-trigger").trigger("click");
    await view.get(".watch-state-action").trigger("click");
    await flushPromises();
    await view.get('[role="dialog"] .button-primary').trigger("click");
    await flushPromises();
    expect(view.get('[role="alert"]').text()).toContain("items.stateConflict");
    expect(view.find('[role="dialog"] .button-primary').exists()).toBe(false);
    expect(view.emitted("changed")).toBeUndefined();
});
it("marks an item directly from its detail action and offers the reverse action", async () => {
    vi.mocked(items.setWatched).mockResolvedValue({ watched: true, state_revision: 4 } as never);
    const view = open();
    await view.setProps({ direct: true });
    expect(view.find(".watch-state-trigger").exists()).toBe(false);
    expect(view.get("button").text()).toBe("items.markWatched");
    await view.get("button").trigger("click");
    await flushPromises();
    expect(items.setWatched).toHaveBeenCalledExactlyOnceWith(7, true, 3);
    expect(view.get("button").text()).toBe("items.markUnwatched");
});
