import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { items, metadata } from "@/api/client";
import EpisodeAssociationForm from "@/components/EpisodeAssociationForm.vue";

vi.mock("@/api/client", () => ({ items: { list: vi.fn() }, metadata: { get: vi.fn(), associateEpisode: vi.fn() } }));
let wrapper: VueWrapper | undefined;
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(items.list).mockImplementation(async (options) =>
        options.kind === "series"
            ? ([{ id: 10, title: "Series" }] as never)
            : options.kind === "season"
              ? ([{ id: 20, title: "Season 1" }] as never)
              : ([
                    { id: 30, title: "Missing episode", season_number: 1, episode_number: 3, availability: "missing" },
                    {
                        id: 31,
                        title: "Another episode",
                        season_number: 1,
                        episode_number: 4,
                        availability: "available",
                    },
                ] as never),
    );
    vi.mocked(metadata.get).mockResolvedValue({
        id: 30,
        title: "Missing episode",
        revision: 11,
        season_number: 1,
        episode_number: 3,
    } as never);
    vi.mocked(metadata.associateEpisode).mockResolvedValue({ item_id: 30 });
});
afterEach(() => {
    wrapper?.unmount();
    wrapper = undefined;
});
async function open() {
    const view = mount(EpisodeAssociationForm, {
        props: { item: { id: 1, title: "Orphan 103", revision: 4, metadata_library_id: 8 } as never },
    });
    wrapper = view;
    await view.get("input").setValue("Series");
    await view.get("form").trigger("submit");
    await flushPromises();
    await view.findAll("select")[0].setValue("10");
    await flushPromises();
    await view.findAll("select")[1].setValue("20");
    await flushPromises();
    return view;
}
it("associates a missing catalogue episode only after explicit confirmation of both revisions", async () => {
    const view = await open();
    expect(items.list).toHaveBeenCalledWith(
        { kind: "series", q: "Series", library_id: 8, skip: 0, limit: 21 },
        expect.any(AbortSignal),
    );
    await view.findAll("select")[2].setValue("30");
    await flushPromises();
    expect(metadata.associateEpisode).not.toHaveBeenCalled();
    await view.get(".button-primary").trigger("click");
    await flushPromises();
    expect(metadata.associateEpisode).toHaveBeenCalledWith(1, 4, 30, 11);
    expect(view.emitted("associated")).toEqual([[30]]);
    expect(view.emitted("busy")).toEqual([[true], [false]]);
});
it("ignores an obsolete target revision after choosing another episode", async () => {
    const view = await open();
    let finish: (value: never) => void = () => {};
    vi.mocked(metadata.get)
        .mockReturnValueOnce(
            new Promise((resolve) => {
                finish = resolve;
            }),
        )
        .mockResolvedValueOnce({ id: 31, title: "Chosen", revision: 15, season_number: 1, episode_number: 4 } as never);
    await view.findAll("select")[2].setValue("30");
    await view.findAll("select")[2].setValue("31");
    await flushPromises();
    finish({ id: 30, title: "Old target", revision: 11 } as never);
    await flushPromises();
    await view.get(".button-primary").trigger("click");
    await flushPromises();
    expect(metadata.associateEpisode).toHaveBeenCalledWith(1, 4, 31, 15);
    expect(vi.mocked(metadata.get).mock.calls[0][1]?.aborted).toBe(true);
});
it("does not navigate or reuse a stale target after a conflict", async () => {
    vi.mocked(metadata.associateEpisode).mockRejectedValue(Object.assign(new Error("Changed"), { status: 409 }));
    const view = await open();
    await view.findAll("select")[2].setValue("30");
    await flushPromises();
    await view.get(".button-primary").trigger("click");
    await flushPromises();
    expect(view.get('[role="alert"]').text()).toBe("metadata.conflict");
    expect(view.find(".button-primary").exists()).toBe(false);
    expect(view.emitted("associated")).toBeUndefined();
    expect(view.emitted("conflict")).toHaveLength(1);
    expect(metadata.associateEpisode).toHaveBeenCalledOnce();
});
