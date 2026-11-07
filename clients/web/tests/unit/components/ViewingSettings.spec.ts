import { flushPromises, mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import { settings } from "@/api/client";
import SettingsPanel from "@/components/SettingsPanel.vue";

vi.mock("@/api/client", () => ({
    settings: { getSettings: vi.fn(), updateSettings: vi.fn(), getHardwareTranscodingStatus: vi.fn() },
}));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));
it("persists only changed watch threshold and next-up retention", async () => {
    const original = {
        library_scan_interval_minutes: 120,
        cleanup_schedule_hour: 3,
        cleanup_schedule_minute: 0,
        cleanup_grace_period_days: 30,
        hardware_transcoding_device: "auto",
        watched_threshold_percent: 90,
        next_up_retention_days: 90,
    };
    vi.mocked(settings.getSettings).mockResolvedValue(original as never);
    vi.mocked(settings.getHardwareTranscodingStatus).mockResolvedValue({ devices: [], warnings: [] } as never);
    vi.mocked(settings.updateSettings).mockResolvedValue({
        ...original,
        watched_threshold_percent: 95,
        next_up_retention_days: 180,
    } as never);
    const view = mount(SettingsPanel);
    await flushPromises();
    expect(view.get<HTMLInputElement>("#watched-threshold").element.value).toBe("90");
    await view.get("#watched-threshold").setValue("95");
    await view.get("#next-up-retention").setValue("180");
    const save = view.findAll("button").find((button) => button.text() === "Save");
    if (!save) throw new Error("Save button missing");
    await save.trigger("click");
    await flushPromises();
    expect(settings.updateSettings).toHaveBeenCalledWith({
        watched_threshold_percent: 95,
        next_up_retention_days: 180,
    });
    view.unmount();
});
