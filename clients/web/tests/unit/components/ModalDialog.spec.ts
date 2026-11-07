import { mount } from "@vue/test-utils";
import { afterEach, expect, it, vi } from "vitest";
import ModalDialog from "@/components/ModalDialog.vue";

const originalShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const originalClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
afterEach(() => {
    for (const [name, descriptor] of [
        ["showModal", originalShow],
        ["close", originalClose],
    ] as const) {
        if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor);
        else Reflect.deleteProperty(HTMLDialogElement.prototype, name);
    }
    document.body.replaceChildren();
});
it("returns keyboard focus to its trigger when the modal is removed", async () => {
    // jsdom lacks the native dialog API; simulate browser opening/focus only.
    const show = vi.fn(function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
        this.querySelector("input")?.focus();
    });
    const close = vi.fn(function (this: HTMLDialogElement) {
        this.removeAttribute("open");
    });
    Object.defineProperties(HTMLDialogElement.prototype, {
        showModal: { value: show, configurable: true },
        close: { value: close, configurable: true },
    });
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const wrapper = mount(ModalDialog, {
        props: { label: "Add library" },
        slots: { default: '<input aria-label="Name">' },
        attachTo: document.body,
    });
    expect(show).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(wrapper.get("input").element);
    await wrapper.get("dialog").trigger("keydown", { key: "Escape" });
    expect(wrapper.emitted("close")).toHaveLength(1);
    wrapper.unmount();
    expect(close).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(trigger);
});
