import { createApp } from "vue";
import App from "./App.vue";
import i18n from "./i18n";
import router from "./router";
import "./style.css";

// Import device profile test in development
if (import.meta.env.DEV) {
  import("./services/deviceProfileTest");
}

createApp(App).use(router).use(i18n).mount("#app");
