# Agent Technical Documentation

Concise technical guidance for AI coding agents working on the Ferelix web client.

## Quick facts

- Package manager: **pnpm** (project has a pinned `packageManager` version in `package.json`).
- Node: **>= 18** (see `engines`).
- Language: **TypeScript** (Vue 3 + TypeScript).
- Dev server: **Vite** (default port 5173) — dev commands run `pnpm generate-version && vite`.

---

## Common tasks (short)

- Install: `pnpm install` (CI caches pnpm & uses `pnpm-lock.yaml`).
- Dev: `pnpm dev` (runs `generate-version` first).
- Build: `pnpm build` (runs `generate-version` then `vite build`).
- Preview: `pnpm preview` / Clean: `pnpm clean`.
- Format / Lint: `pnpm check --fix` (biome).
- Type-check: `pnpm type-check` (vue-tsc).

Note: `scripts/generate-version.js` must run before dev/build; it's included in `dev` and `build` scripts.

---

## CI / Release

- GitHub Actions workflow `.github/workflows/build-and-release.yml` caches pnpm and runs `pnpm install` then `pnpm build`.

---

## Development conventions (for agents)

- Components: `src/components/` (PascalCase, single-file `.vue`).
- Views: `src/views/` and routing in `src/router/`.
- API: centralized in `src/api/client.js` (token refresh + concurrency handling). Update here for new endpoints.
- i18n: add keys to `src/i18n/locales/en.json` and `fr.json` when adding text.
- Styling: Tailwind CSS (`tailwind.config.js`) and `src/style.css`.

---

## Proxy & runtime

- Dev proxy: Vite proxies `/api` → `http://localhost:8000` (configured in `vite.config.js`) to avoid CORS during development.
- Path alias: `@` resolves to `src/` (used throughout the codebase).

---

## Helpful tips

- When adding UI, wire up translations in both locales and add simple unit/e2e tests where appropriate (no tests are present yet).
- For streaming, `hls.js` is used in `VideoPlayer.vue` to handle HLS gracefully (native HLS supported on Safari).
