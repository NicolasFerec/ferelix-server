import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { libraries } from "@/api/client";
import LibraryForm from "@/components/LibraryForm.vue";

vi.mock("@/api/client", () => ({ libraries: { createLibrary: vi.fn(), updateLibrary: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
it("saves per-library metadata settings with the library configuration", async () => {
    vi.mocked(libraries.createLibrary).mockResolvedValue({ id: 1 } as never);
    const view = mount(LibraryForm, {
        global: { stubs: { ModalDialog: { template: "<div><slot/></div>" }, DirectoryBrowser: true } },
    });
    await view.get("#library-name").setValue(" Anime ");
    await view.get("#library-path").setValue("/media/anime");
    await view.get("#library-type").setValue("tv_show");
    await view.get("#metadata-locale").setValue("ja-JP");
    await view.get("#metadata-profile").setValue("anime");
    await view.findAll('input[type="checkbox"]')[0].setValue(true);
    await view.get("form").trigger("submit");
    await flushPromises();
    expect(libraries.createLibrary).toHaveBeenCalledWith({
        name: "Anime",
        path: "/media/anime",
        library_type: "tv_show",
        enabled: true,
        metadata_locale: "ja-JP",
        metadata_profile: "anime",
        metadata_export_nfo: true,
    });
    expect(view.emitted("saved")).toHaveLength(1);
    view.unmount();
});
