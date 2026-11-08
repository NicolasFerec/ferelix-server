import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { auth, isAuthenticated } from "@/api/client";

const routes: RouteRecordRaw[] = [
    { path: "/items/:id", name: "item-detail", component: () => import("../views/ItemDetailView.vue") },
    { path: "/search", name: "search", component: () => import("../views/DiscoveryView.vue") },
    { path: "/watchlist", name: "watchlist", component: () => import("../views/DiscoveryView.vue") },
    {
        path: "/",
        name: "home",
        component: () => import("../views/HomeView.vue"),
    },
    {
        path: "/media/:id",
        name: "media-detail",
        component: () => import("../views/MediaDetailView.vue"),
        props: true,
    },
    {
        path: "/play/:id",
        name: "player",
        component: () => import("../views/PlayerView.vue"),
        props: true,
    },
    {
        path: "/library/:id",
        name: "library",
        component: () => import("../views/LibraryView.vue"),
        props: true,
    },
    {
        path: "/login",
        name: "login",
        component: () => import("../views/LoginView.vue"),
    },
    {
        path: "/setup",
        name: "setup",
        component: () => import("../views/SetupView.vue"),
    },
    {
        path: "/settings",
        name: "settings",
        component: () => import("../views/UserSettingsView.vue"),
    },
    {
        path: "/dashboard/:section?",
        name: "dashboard",
        component: () => import("../views/DashboardView.vue"),
    },
];

const router = createRouter({
    history: createWebHistory(),
    routes,
    scrollBehavior: (_to, _from, savedPosition) => savedPosition || { top: 0 },
});

// Global navigation guard for authentication and admin routes
router.beforeEach(async (to, _from, next) => {
    const publicPages = ["/login", "/setup"];
    const authRequired = !publicPages.includes(to.path);
    const isAdminPage = to.path === "/dashboard" || to.path.startsWith("/dashboard/");

    // Check authentication
    if (authRequired && !isAuthenticated()) {
        next({ name: "login", query: { redirect: to.fullPath } });
        return;
    }

    // Check admin access for admin-only pages
    if (isAdminPage) {
        try {
            const user = await auth.getCurrentUser();
            if (!user?.is_admin) {
                next("/");
                return;
            }
        } catch (error) {
            console.error("Failed to check admin status:", error);
            next(isAuthenticated() ? "/" : { name: "login", query: { redirect: to.fullPath } });
            return;
        }
    }

    next();
});

export default router;
