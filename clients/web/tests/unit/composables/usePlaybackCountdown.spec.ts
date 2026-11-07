import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { defineComponent } from "vue";
import { usePlaybackCountdown } from "@/composables/usePlaybackCountdown";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
function createCountdown() {
    const complete = vi.fn();
    let countdown: ReturnType<typeof usePlaybackCountdown> | undefined;
    const wrapper = mount(
        defineComponent({
            setup() {
                countdown = usePlaybackCountdown(complete);
                return () => null;
            },
        }),
    );
    if (!countdown) throw new Error("Countdown not mounted");
    return { wrapper, complete, countdown };
}
it("does not advance before an explicit start and waits ten seconds afterwards", async () => {
    const { wrapper, complete, countdown } = createCountdown();
    await vi.advanceTimersByTimeAsync(20000);
    expect(complete).not.toHaveBeenCalled();
    countdown.start();
    await vi.advanceTimersByTimeAsync(9000);
    expect(countdown.remaining.value).toBe(1);
    expect(complete).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(complete).toHaveBeenCalledOnce();
    expect(countdown.active.value).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    wrapper.unmount();
});
it("cancels on user interaction and on route unmount", async () => {
    const { wrapper, complete, countdown } = createCountdown();
    countdown.start();
    await vi.advanceTimersByTimeAsync(5000);
    countdown.cancel();
    await vi.advanceTimersByTimeAsync(10000);
    expect(complete).not.toHaveBeenCalled();
    countdown.start();
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(10000);
    expect(complete).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
});
it("replaces an old countdown without leaving another completion timer", async () => {
    const { wrapper, complete, countdown } = createCountdown();
    countdown.start();
    await vi.advanceTimersByTimeAsync(5000);
    countdown.start();
    await vi.advanceTimersByTimeAsync(5000);
    expect(complete).not.toHaveBeenCalled();
    expect(countdown.remaining.value).toBe(5);
    await vi.advanceTimersByTimeAsync(5000);
    expect(complete).toHaveBeenCalledOnce();
    wrapper.unmount();
});
