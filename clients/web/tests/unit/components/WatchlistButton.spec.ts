import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { watchlist } from "@/api/client";
import WatchlistButton from "@/components/WatchlistButton.vue";

vi.mock("@/api/client", () => ({ watchlist: { add: vi.fn(), remove: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
it("shows only the confirmed list state and serializes repeat clicks", async () => {
    let complete: (result: never) => void = () => {};
    vi.mocked(watchlist.add).mockReturnValue(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const wrapper = mount(WatchlistButton, { props: { mediaId: 5, inWatchlist: false } });
    await wrapper.get("button").trigger("click");
    await wrapper.get("button").trigger("click");
    expect(watchlist.add).toHaveBeenCalledExactlyOnceWith(5);
    expect(wrapper.get("button").attributes("aria-pressed")).toBe("false");
    expect(wrapper.emitted("updated")).toBeUndefined();
    complete({ media_file_id: 5, in_watchlist: true } as never);
    await flushPromises();
    expect(wrapper.emitted("updated")).toEqual([[true]]);
    await wrapper.setProps({ inWatchlist: true });
    vi.mocked(watchlist.remove).mockResolvedValue({ media_file_id: 5, in_watchlist: false });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(watchlist.remove).toHaveBeenCalledExactlyOnceWith(5);
    expect(wrapper.emitted("updated")?.at(-1)).toEqual([false]);
    wrapper.unmount();
});
it("retains the confirmed state when an update fails", async () => {
    vi.mocked(watchlist.remove).mockRejectedValue(new Error("Unavailable"));
    const wrapper = mount(WatchlistButton, { props: { mediaId: 5, inWatchlist: true } });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get("button").attributes("aria-pressed")).toBe("true");
    expect(wrapper.emitted("updated")).toBeUndefined();
    expect(wrapper.get('[role="alert"]').text()).toBe("watchlist.updateFailed");
    expect(wrapper.get("button").attributes("disabled")).toBeUndefined();
    wrapper.unmount();
});
