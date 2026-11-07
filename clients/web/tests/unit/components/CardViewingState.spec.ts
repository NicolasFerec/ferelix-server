import { mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import ItemCard from "@/components/ItemCard.vue";
import MediaCard from "@/components/MediaCard.vue";

vi.mock("@/api/client", () => ({ items: { artworkUrl: () => null }, media: { getThumbnailUrl: () => "/thumbnail" } }));
const global = { stubs: { RouterLink: { template: "<a><slot/></a>" }, WatchStateMenu: true } };
it("uses server segment progress independently from physical file position", () => {
    const view = mount(ItemCard, {
        props: {
            item: {
                id: 1,
                kind: "episode",
                title: "Episode",
                position_seconds: 2500,
                duration_seconds: 5000,
                progress_percent: 25,
                resume_active: true,
                watched: true,
                availability: "available",
            } as never,
        },
        global,
    });
    expect(view.get('[role="progressbar"]').attributes("aria-valuenow")).toBe("25");
    const badge = view.get('[role="img"][aria-label="mediaDetail.watched"]');
    expect(badge.classes()).toEqual(expect.arrayContaining(["top-2", "right-2"]));
    expect(view.get("a").attributes("aria-label")).toBe("Episode · mediaDetail.watched");
    expect(view.get("watch-state-menu-stub").element.parentElement?.classList.contains("absolute")).toBe(true);
    view.unmount();
});
it("hides progress for an unavailable or ambiguous resume without hiding watched state", () => {
    const view = mount(ItemCard, {
        props: {
            item: {
                id: 1,
                kind: "episode",
                title: "Episode",
                progress_percent: 90,
                resume_active: false,
                watched: true,
                availability: "available",
            } as never,
        },
        global,
    });
    expect(view.find('[role="progressbar"]').exists()).toBe(false);
    const badge = view.get('[role="img"][aria-label="mediaDetail.watched"]');
    expect(badge.classes()).toEqual(expect.arrayContaining(["top-2", "right-2"]));
    expect(view.get("a").attributes("aria-label")).toBe("Episode · mediaDetail.watched");
    expect(view.get("watch-state-menu-stub").element.parentElement?.classList.contains("absolute")).toBe(true);
    view.unmount();
});
it("shows actual rewatch progress on physical recommendation cards", () => {
    const view = mount(MediaCard, {
        props: {
            mediaFile: {
                id: 1,
                file_name: "Film.mkv",
                item_id: 10,
                duration: 1000,
                watched: true,
                user_view: { position_seconds: 250, duration_seconds: 1000, watched: true, resume_active: true },
            } as never,
        },
        global,
    });
    expect(view.get('[role="progressbar"]').attributes("aria-valuenow")).toBe("25");
    expect(view.get('[role="img"][aria-label="mediaDetail.watched"]').classes()).toEqual(
        expect.arrayContaining(["top-2", "right-2"]),
    );
    expect(view.get("watch-state-menu-stub").element.parentElement?.classList.contains("absolute")).toBe(true);
    expect(view.get("a").attributes("aria-label")).toBe("Film · mediaDetail.watched");
    view.unmount();
});
