import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import { auth } from "@/api/client";
import PlaybackPreferencesForm from "@/components/PlaybackPreferencesForm.vue";

vi.mock("@/api/client", () => ({ auth: { updateCurrentUser: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
it.each(["fr-ca", "zzz", "en-12"])("preserves an existing regional or unfamiliar language %s", async (language) => {
    const user = {
        id: 1,
        preferred_audio_language: language,
        preferred_subtitle_language: "ja",
        subtitle_mode: "always",
    } as never;
    vi.mocked(auth.updateCurrentUser).mockResolvedValue(user);
    const wrapper = mount(PlaybackPreferencesForm, { props: { user } });
    expect((wrapper.get("#preferred-audio").element as HTMLSelectElement).value).toBe(language);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(auth.updateCurrentUser).toHaveBeenCalledWith({
        autoplay_next_episode: true,
        preferred_audio_language: language,
        preferred_subtitle_language: "ja",
        subtitle_mode: "always",
    });
    expect(wrapper.emitted("saved")).toEqual([[user]]);
    expect(wrapper.find('[role="status"]').exists()).toBe(true);
    wrapper.unmount();
});
it("keeps the subtitle language while turning automatic subtitles off", async () => {
    const wrapper = mount(PlaybackPreferencesForm, {
        props: {
            user: {
                id: 1,
                preferred_audio_language: null,
                preferred_subtitle_language: "fr",
                subtitle_mode: "always",
            } as never,
        },
    });
    vi.mocked(auth.updateCurrentUser).mockRejectedValue(new Error("Unavailable"));
    await wrapper.get("#subtitle-mode").setValue("off");
    expect(wrapper.find("#preferred-subtitle").exists()).toBe(false);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(auth.updateCurrentUser).toHaveBeenCalledWith({
        autoplay_next_episode: true,
        preferred_audio_language: null,
        preferred_subtitle_language: "fr",
        subtitle_mode: "off",
    });
    expect(wrapper.emitted("saved")).toBeUndefined();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    wrapper.unmount();
});

it("persists disabled next-episode autoplay only on submit", async () => {
    const wrapper = mount(PlaybackPreferencesForm, {
        props: { user: { id: 1, autoplay_next_episode: true, subtitle_mode: "off" } as never },
    });
    vi.mocked(auth.updateCurrentUser).mockResolvedValue({ id: 1, autoplay_next_episode: false } as never);
    await wrapper.get('input[type="checkbox"]').setValue(false);
    expect(auth.updateCurrentUser).not.toHaveBeenCalled();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(auth.updateCurrentUser).toHaveBeenCalledWith(expect.objectContaining({ autoplay_next_episode: false }));
    wrapper.unmount();
});
