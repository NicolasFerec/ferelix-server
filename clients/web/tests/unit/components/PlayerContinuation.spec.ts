import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ref } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { items, media } from "@/api/client";
import CustomVideoPlayer from "@/components/CustomVideoPlayer.vue";
import PlayerView from "@/views/PlayerView.vue";

const preference = vi.hoisted(() => ({ autoplay: true }));
vi.mock("@/api/client", () => ({
    items: { get: vi.fn(), forFile: vi.fn(), continuation: vi.fn() },
    media: { getMediaFile: vi.fn() },
}));
vi.mock("@/composables/useUser", () => ({
    useUser: () => ({ user: ref({ autoplay_next_episode: preference.autoplay }), loadUser: vi.fn() }),
}));
vi.mock("@/components/CustomVideoPlayer.vue", () => ({
    default: {
        props: [
            "mediaFile",
            "itemId",
            "continuationFromItemId",
            "initialPositionSeconds",
            "restoreState",
            "initialAudioStreamIndex",
            "initialSubtitleStreamIndex",
        ],
        emits: ["ended", "activity", "close", "restore"],
        template: '<div class="fake-player" />',
    },
}));
let wrapper: VueWrapper | undefined;
beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers();
    preference.autoplay = true;
    vi.mocked(media.getMediaFile).mockImplementation(async (id) => ({ id, item_id: id === 1 ? 11 : 12 }) as never);
    vi.mocked(items.get).mockImplementation(
        async (id) =>
            ({
                id,
                kind: "episode",
                title: `Episode ${id}`,
                playable_file_id: id === 11 ? 1 : 2,
                series_id: 10,
                parent_id: 20,
            }) as never,
    );
    vi.mocked(items.continuation).mockResolvedValue({
        status: "ready",
        item: { id: 12, title: "Second episode", series_id: 10, parent_id: 20 },
        media_file_id: 2,
        position_seconds: 1200,
    } as never);
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
            { path: "/player/:id", name: "player", component: PlayerView },
            { path: "/items/:id", name: "item-detail", component: { template: "<div/>" } },
        ],
    });
    await router.push("/player/1?item=11&audio=4&subtitle=-1&returnTo=/items/11");
    const view = mount(PlayerView, { global: { plugins: [router] } });
    wrapper = view;
    await flushPromises();
    return { view, router };
}
it("does not request a successor until actual ended and waits ten seconds", async () => {
    const { view, router } = await open();
    await vi.advanceTimersByTimeAsync(20000);
    expect(items.continuation).not.toHaveBeenCalled();
    view.getComponent(CustomVideoPlayer).vm.$emit("ended");
    await flushPromises();
    expect(items.continuation).toHaveBeenCalledWith(11, "next", expect.any(AbortSignal));
    await vi.advanceTimersByTimeAsync(9999);
    expect(router.currentRoute.value.params.id).toBe("1");
    await vi.advanceTimersByTimeAsync(1);
    await flushPromises();
    expect(router.currentRoute.value.params.id).toBe("2");
    expect(router.currentRoute.value.query).toEqual({
        item: "12",
        position: "1200",
        continuationFrom: "11",
        returnTo: "/items/11",
    });
    expect(view.getComponent(CustomVideoPlayer).props()).toMatchObject({
        itemId: 12,
        initialPositionSeconds: 1200,
        continuationFromItemId: 11,
    });
});
it.each(["missing", "upcoming", "unknown_order", "complete"])(
    "does not autoplay or skip a %s next episode",
    async (status) => {
        vi.mocked(items.continuation).mockResolvedValue({
            status,
            item: { id: 12, title: "Unavailable" },
            media_file_id: null,
            position_seconds: 0,
        } as never);
        const { view, router } = await open();
        view.getComponent(CustomVideoPlayer).vm.$emit("ended");
        await flushPromises();
        await vi.advanceTimersByTimeAsync(20000);
        expect(router.currentRoute.value.params.id).toBe("1");
        expect(view.text()).toContain(`items.continuation.${status}`);
        expect(view.find(".button-primary").exists()).toBe(false);
    },
);
it("keeps a manual next action when autoplay is disabled", async () => {
    preference.autoplay = false;
    const { view, router } = await open();
    view.getComponent(CustomVideoPlayer).vm.$emit("ended");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(20000);
    expect(router.currentRoute.value.params.id).toBe("1");
    await view.get(".button-primary").trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.params.id).toBe("2");
});
it("ignores late continuation after a seek or replay action", async () => {
    let complete: (value: never) => void = () => {};
    vi.mocked(items.continuation).mockReturnValue(
        new Promise((resolve) => {
            complete = resolve;
        }),
    );
    const { view, router } = await open();
    view.getComponent(CustomVideoPlayer).vm.$emit("ended");
    await flushPromises();
    view.getComponent(CustomVideoPlayer).vm.$emit("activity");
    complete({ status: "ready", item: { id: 12 }, media_file_id: 2, position_seconds: 0 } as never);
    await flushPromises();
    await vi.advanceTimersByTimeAsync(15000);
    expect(router.currentRoute.value.params.id).toBe("1");
    expect(vi.mocked(items.continuation).mock.calls[0][2]?.aborted).toBe(true);
});
it("cancels an active countdown on close and on unmount", async () => {
    const { view, router } = await open();
    view.getComponent(CustomVideoPlayer).vm.$emit("ended");
    await flushPromises();
    view.getComponent(CustomVideoPlayer).vm.$emit("close");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(15000);
    expect(router.currentRoute.value.path).toBe("/items/11");
});

it("opens the containing season from an unavailable next episode panel", async () => {
    vi.mocked(items.continuation).mockResolvedValue({
        status: "missing",
        item: { id: 12, title: "Missing", series_id: 10, parent_id: 20 },
        media_file_id: null,
        position_seconds: 0,
    } as never);
    const { view, router } = await open();
    view.getComponent(CustomVideoPlayer).vm.$emit("ended");
    await flushPromises();
    const season = view.get('a[href="/items/10?season=20"]');
    await season.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/items/10?season=20");
});
it("recreates the player on bfcache restore and cancels a prior next-episode countdown", async () => {
    const { view, router } = await open();
    const oldPlayer = view.getComponent(CustomVideoPlayer);
    oldPlayer.vm.$emit("ended");
    await flushPromises();
    const state = { positionSeconds: 123, playing: false, audioStreamIndex: 2, subtitleStreamIndex: -1 };
    oldPlayer.vm.$emit("activity");
    oldPlayer.vm.$emit("restore", state);
    await flushPromises();
    const restored = view.getComponent(CustomVideoPlayer);
    expect(restored.vm).not.toBe(oldPlayer.vm);
    expect(restored.props("restoreState")).toEqual(state);
    await vi.advanceTimersByTimeAsync(15000);
    expect(router.currentRoute.value.params.id).toBe("1");
});
