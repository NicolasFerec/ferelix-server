import { flushPromises, mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import { metadata } from "@/api/client";
import MetadataJobsPanel from "@/components/MetadataJobsPanel.vue";

vi.mock("@/api/client", () => ({ metadata: { jobs: vi.fn() } }));
it("filters completed jobs using the server done status and a bounded page", async () => {
    vi.mocked(metadata.jobs).mockResolvedValue([]);
    const view = mount(MetadataJobsPanel);
    await flushPromises();
    expect(view.find('option[value="done"]').exists()).toBe(true);
    expect(view.find('option[value="completed"]').exists()).toBe(false);
    await view.get("select").setValue("done");
    await flushPromises();
    expect(metadata.jobs).toHaveBeenLastCalledWith("done", 0, 49, expect.any(AbortSignal));
    view.unmount();
});
