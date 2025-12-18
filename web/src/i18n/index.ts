import { createI18n } from "vue-i18n";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

type SupportedLocale = "en" | "fr";

// Detect browser language
function detectLanguage(): SupportedLocale {
  const browserLang =
    navigator.language || (navigator as Navigator & { userLanguage?: string }).userLanguage || "en";
  const langCode = browserLang.split("-")[0].toLowerCase();

  // Supported languages: en, fr
  if (langCode === "fr") {
    return "fr";
  }

  // Default to English
  return "en";
}

const i18n = createI18n({
  legacy: false,
  locale: detectLanguage(),
  fallbackLocale: "en" as SupportedLocale,
  messages: {
    en,
    fr,
  },
});

export default i18n;
export type { SupportedLocale };
