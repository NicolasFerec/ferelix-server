import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { media } from "@/api/client";
import DropdownSelect from "@/components/DropdownSelect.vue";
import MediaDetailView from "@/views/MediaDetailView.vue";

vi.mock("@/api/client", () => ({
    media: { getMediaFile: vi.fn(), getThumbnailUrl: () => "/thumbnail" },
    watchlist: {},
}));
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(media.getMediaFile).mockResolvedValue({
        id: 5,
        file_name: "Film.mkv",
        duration: 1200,
        in_watchlist: true,
        video_tracks: [{ stream_index: 0, is_default: true }],
        audio_tracks: [
            { id: 1, stream_index: 1, is_default: true },
            { id: 2, stream_index: 2 },
        ],
        subtitle_tracks: [{ id: 3, stream_index: 3, codec: "subrip" }],
    } as never);
});
it("starts with automatic preferences and carries only explicitly selected audio/subtitles", async () => {
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [
            { path: "/media/:id", name: "media-detail", component: MediaDetailView },
            { path: "/play/:id", name: "player", component: { template: "<div/>" } },
        ],
    });
    await router.push({ name: "media-detail", params: { id: 5 }, query: { returnTo: "/search?q=film&page=2" } });
    const wrapper = mount(MediaDetailView, {
        global: { plugins: [router], stubs: { MenuBar: true, WatchlistButton: true, DropdownSelect: true } },
    });
    await flushPromises();
    let destination = new URL(wrapper.get<HTMLAnchorElement>('a[href^="/play/"]').element.href, "http://localhost");
    expect(destination.searchParams.has("audio")).toBe(false);
    expect(destination.searchParams.has("subtitle")).toBe(false);
    expect(wrapper.get('a[href^="/search"]').attributes("href")).toBe("/search?q=film&page=2");
    const selects = wrapper.findAllComponents(DropdownSelect);
    selects[1].vm.$emit("update:modelValue", 2);
    await flushPromises();
    selects[2].vm.$emit("update:modelValue", -1);
    await flushPromises();
    destination = new URL(wrapper.get<HTMLAnchorElement>('a[href^="/play/"]').element.href, "http://localhost");
    expect(destination.searchParams.get("audio")).toBe("2");
    expect(destination.searchParams.get("subtitle")).toBe("-1");
    expect(media.getMediaFile).toHaveBeenCalledOnce();
    wrapper.unmount();
});
