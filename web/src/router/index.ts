import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { auth, isAuthenticated } from "@/api/client";
import DashboardView from "../views/DashboardView.vue";
import HomeView from "../views/HomeView.vue";
import LibraryView from "../views/LibraryView.vue";
import LoginView from "../views/LoginView.vue";
import MediaDetailView from "../views/MediaDetailView.vue";
import PlayerView from "../views/PlayerView.vue";
import SetupView from "../views/SetupView.vue";
import UserSettingsView from "../views/UserSettingsView.vue";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    component: HomeView,
  },
  {
    path: "/media/:id",
    name: "media-detail",
    component: MediaDetailView,
    props: true,
  },
  {
    path: "/play/:id",
    name: "player",
    component: PlayerView,
    props: true,
  },
  {
    path: "/library/:id",
    name: "library",
    component: LibraryView,
    props: true,
  },
  {
    path: "/login",
    name: "login",
    component: LoginView,
  },
  {
    path: "/setup",
    name: "setup",
    component: SetupView,
  },
  {
    path: "/settings",
    name: "settings",
    component: UserSettingsView,
  },
  {
    path: "/dashboard",
    name: "dashboard",
    component: DashboardView,
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Global navigation guard for authentication and admin routes
router.beforeEach(async (to, _from, next) => {
  const publicPages = ["/login", "/setup"];
  const authRequired = !publicPages.includes(to.path);
  const adminPages = ["/dashboard"];

  // Check authentication
  if (authRequired && !isAuthenticated()) {
    next("/login");
    return;
  }

  // Check admin access for admin-only pages
  if (adminPages.includes(to.path)) {
    try {
      const user = await auth.getCurrentUser();
      if (!user || !user.is_admin) {
        next("/");
        return;
      }
    } catch (error) {
      console.error("Failed to check admin status:", error);
      next("/");
      return;
    }
  }

  next();
});

export default router;
