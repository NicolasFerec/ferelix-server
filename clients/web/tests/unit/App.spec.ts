import { mount } from "@vue/test-utils";
import { expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, useRoute } from "vue-router";
import App from "@/App.vue";

vi.mock("@/composables/useUser", () => ({ useUser: () => ({ loadUser: async () => null }) }));

it("reloads a route component when navigating between library IDs", async () => {
    const library = defineComponent({
        setup() {
            const initialId = useRoute().params.id;
            return () => h("p", `Library ${initialId}`);
        },
    });
    const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: "/library/:id", component: library }],
    });
    await router.push("/library/1");
    const wrapper = mount(App, { global: { plugins: [router], stubs: { ToastViewport: true } } });
    expect(wrapper.text()).toContain("Library 1");
    await router.push("/library/2");
    expect(wrapper.text()).toContain("Library 2");
    wrapper.unmount();
});
