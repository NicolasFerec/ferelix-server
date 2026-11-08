import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { metadata } from "@/api/client";
import MetadataEditor from "@/components/MetadataEditor.vue";

vi.mock("@/api/client", () => ({
    metadata: {
        get: vi.fn(),
        update: vi.fn(),
        providers: vi.fn(),
        search: vi.fn(),
        identify: vi.fn(),
        refresh: vi.fn(),
        restore: vi.fn(),
        uploadImage: vi.fn(),
    },
}));
let wrapper: VueWrapper | undefined;
const item = {
    id: 1,
    kind: "movie",
    title: "Original",
    revision: 7,
    locked: false,
    locked_fields: ["overview"],
    metadata_locale: "fr-FR",
    metadata_status: "ready",
    aliases: [],
    genres: [{ name: "Drama" }],
    keywords: [],
    credits: [],
    studios: [],
    countries: [],
    provider_ids: { tmdb: "10" },
};
beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(metadata.get).mockResolvedValue(item as never);
    vi.mocked(metadata.providers).mockResolvedValue({
        tmdb_configured: true,
        anidb_configured: false,
        metadata_dir: "/metadata",
    });
});
afterEach(() => wrapper?.unmount());
async function open() {
    const view = mount(MetadataEditor, {
        props: { itemId: 1 },
        global: {
            stubs: { ModalDialog: { template: "<div><slot/></div>" }, RouterLink: { template: "<a><slot/></a>" } },
        },
    });
    wrapper = view;
    await flushPromises();
    return view;
}
it("submits only changed values with current revision and preserved locks", async () => {
    vi.mocked(metadata.update).mockResolvedValue({ ...item, title: "New" } as never);
    const view = await open();
    await view.get("#metadata-title").setValue("New");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(metadata.update).toHaveBeenCalledWith(1, {
        expected_revision: 7,
        changes: { title: "New" },
        locked_fields: ["overview"],
        locked: false,
    });
    expect(view.emitted("saved")).toHaveLength(1);
});
it("rejects malformed structured data without sending a mutation", async () => {
    const view = await open();
    await view.get("#metadata-genres").setValue("{broken");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(metadata.update).not.toHaveBeenCalled();
    expect(view.get('[role="alert"]').text()).toContain("metadata.invalidJson");
});
it("shows a revision conflict and never reports a successful save", async () => {
    vi.mocked(metadata.update).mockRejectedValue(Object.assign(new Error("changed"), { status: 409 }));
    const view = await open();
    await view.get("#metadata-title").setValue("New");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(view.get('[role="alert"]').text()).toContain("metadata.conflict");
    expect(view.emitted("saved")).toBeUndefined();
});
it("shows provider failure with retry instead of silently disabling search", async () => {
    vi.mocked(metadata.providers).mockRejectedValueOnce(new Error("offline"));
    const view = await open();
    expect(view.get('[role="alert"]').text()).toContain("metadata.providersFailed");
    await view.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(metadata.providers).toHaveBeenCalledTimes(2);
    expect(view.find('[role="alert"]').exists()).toBe(false);
});
it("aborts identification searches when the editor closes", async () => {
    vi.mocked(metadata.search).mockReturnValue(new Promise(() => {}));
    const view = await open();
    await view.get("#metadata-query").setValue("Title");
    await view.findAll("form")[1].trigger("submit");
    expect(metadata.search).toHaveBeenCalledWith("Title", "movie", "fr-FR", "tmdb", expect.any(AbortSignal));
    view.unmount();
    wrapper = undefined;
    expect(vi.mocked(metadata.search).mock.calls[0][4]?.aborted).toBe(true);
});
it("keeps local refresh usable without remote providers and hides episode-only fields for films", async () => {
    vi.mocked(metadata.providers).mockResolvedValue({
        tmdb_configured: false,
        anidb_configured: false,
        metadata_dir: "/metadata",
    });
    const view = await open();
    expect(view.find("#metadata-season_number").exists()).toBe(false);
    expect(view.find("#metadata-episode_number").exists()).toBe(false);
    const refresh = view.findAll("button").find((button) => button.text() === "metadata.refreshMissing");
    expect(refresh).toBeDefined();
    if (!refresh) throw new Error("Missing refresh action");
    expect(refresh.attributes("disabled")).toBeUndefined();
    await refresh.trigger("click");
    await flushPromises();
    expect(metadata.refresh).toHaveBeenCalledWith(1, 7, "missing");
});
it("uses the returned revision without a follow-up GET after synchronous edits", async () => {
    const view = await open();
    vi.mocked(metadata.update).mockResolvedValue({
        ...item,
        title: "Updated",
        revision: 8,
        locked_fields: ["overview", "title"],
    } as never);
    vi.mocked(metadata.get).mockRejectedValue(new Error("GET unavailable"));
    await view.get("#metadata-title").setValue("Updated");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(metadata.get).toHaveBeenCalledTimes(1);
    expect(view.find('[role="alert"]').exists()).toBe(false);
    await view.get("#metadata-title").setValue("Again");
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(metadata.update).toHaveBeenLastCalledWith(
        1,
        expect.objectContaining({ expected_revision: 8, changes: { title: "Again" } }),
    );
});
it("offers an explicit reload when a queued update cannot refresh its revision", async () => {
    const view = await open();
    vi.mocked(metadata.refresh).mockResolvedValue({ id: 9, status: "pending" } as never);
    vi.mocked(metadata.get).mockRejectedValueOnce(new Error("GET unavailable"));
    const refresh = view.findAll("button").find((button) => button.text() === "metadata.refreshMissing");
    if (!refresh) throw new Error("Missing refresh");
    await refresh.trigger("click");
    await flushPromises();
    expect(view.find('[role="status"]').exists()).toBe(false);
    expect(view.get('[role="alert"] button').text()).toBe("metadata.reload");
    vi.mocked(metadata.get).mockResolvedValue({ ...item, revision: 12 } as never);
    await view.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(view.find('[role="alert"]').exists()).toBe(false);
});
it("requires association to place an unresolved episode instead of editing disconnected numbers", async () => {
    vi.mocked(metadata.get).mockResolvedValue({
        ...item,
        kind: "episode",
        season_number: null,
        episode_number: 103,
        can_associate_episode: true,
        metadata_library_id: 8,
    } as never);
    const view = await open();
    expect(view.find("#metadata-season_number").exists()).toBe(false);
    expect(view.find("#metadata-episode_number").exists()).toBe(false);
    expect(view.text()).toContain("metadata.associateEpisode");
});
