# Internationalization

Status: foundation (2026-09-02). English (`en`) is the source language and fallback. Spanish (`es`) is the second catalog. This document is the boy-scout rule for later PRs. Remaining slices: `docs/development/SLICE_QUEUE.md`.

The first PR only wired the infrastructure and a small pilot (global navigation, canonical entity names, Settings). Do not translate the rest of the app in one change.

## Catalogs

Typed JSON under `ui/src/i18n/locales/<lng>/<namespace>.json`.

| Namespace | Use |
|---|---|
| `common` | Shared actions, status presentation, plurals |
| `navigation` | Tabs, entity names, output folders, labs |
| `settings` | Settings drawer and language selector |
| `wizard` | Ask to the Wizard chrome |
| `activity` | Activity footer, Inbox / Legacy, Extra info inspector, Assets catalog chrome |
| `extraInfo` | Video Extra info dialog body (title stays `activity.extraInfo`) |
| `storyLab` | Story Lab section chrome, world/characters/relationships/structure tabs, reference gallery and editors |
| `director` | Director queue recovery, spoken-language chrome and direct-video T2V mode |
| `seriesLab` | Series Lab tabs, review assembly, shot-duration chrome and spoken-language labels |
| `videoEditor` | Video Editor transitions, time cards, remake and trim chrome |
| `workspaces` | Production runs panel and Workspace collections |
| `styleSheet` | Style sheet library, import and delete chrome |
| `projects` | Durable projects catalog |
| `auditDev` | Internal audio-hallucination audit panel |

Add a namespace only when a new product surface needs its own file. Do not grow a single giant JSON.

Keys are semantic, never the English sentence:

- Correct: `wizard.title`
- Incorrect: `Ask to the Wizard`

## Language, persistence, fallback

- Detected order: `localStorage` key `hocuspocus-ui-language` → `navigator.language` (`es*` → `es`, otherwise `en`) → `en`.
- Changing language calls `setUiLanguage`, writes storage, sets `document.documentElement.lang`, and re-renders without a reload.
- Missing keys fall back to English, then to the key itself. They must not throw.
- Interpolation uses `escapeValue: false` so React text nodes are not
  double-escaped. Do not put HTML in catalog strings.

## Glossary (human labels only)

| Canonical (code / EN UI) | ES |
|---|---|
| Project | Proyecto |
| Production | Producción |
| Run | Ejecución |
| Task | Tarea |
| Asset | Recurso |
| **Workspace** | **Workspace** (product name; do not use «espacio de trabajo») |
| All Workspaces | Todos los Workspaces |
| Output folder | Carpeta de salida |
| Story Lab | Story Lab |
| Series Lab | Series Lab |
| Director | Director |
| Activity | Actividad |
| Ask to the Wizard | Pregunta al mago |
| Inbox / Legacy | Inbox / Legacy |
| Uploads | Subidas |
| Extra info | Información adicional |

Do not translate IDs, schema names, API paths, capability names, action types, filenames, model names, user prompts or generated content.

Internal state `running` stays `running`. Presentation: EN “Running”, ES “En marcha” (`common.status.running`).

## How to add a key

1. Add it to **both** `en` and `es` in the same namespace.
2. Use `useUiTranslation('navigation')` from `ui/src/i18n` (it initializes the singleton). Do not call `useTranslation` from `react-i18next` directly in views.
3. Interpolate with `t('workspace.created', { name })`. Never concatenate `t('created') + name`.
4. Plurals: `t('count.item', { count })` with `item_one` / `item_other`.
5. Run `ui/tests/i18nFoundation.test.tsx` (catalog parity is part of `npm test`).

## What not to translate

- User-written prompts and generated media metadata
- Model names, LoRA filenames, enum/API contract values
- Routes, JSON keys, capability `type` strings
- Python backend errors in this phase (see below)

## Backend errors (future)

Keep JSON contracts as they are. Later:

- backend returns structured `code` + diagnostic `message`
- UI maps known codes through the catalog
- raw backend `message` remains the fallback and the log line

Do not mass-translate Python exceptions in an i18n PR.

## Boy scout (every later UI PR)

When a PR touches a UI zone:

1. Move visible labels, placeholders, titles, tooltips, empty states, visible errors, confirmations and human aria-labels of **that zone** into the catalog.
2. Add EN and ES in the same commit.
3. Follow the glossary; if a term is new, update this document first and use one form.
4. Do not translate files outside the touched zone to inflate stats.
5. Say in the PR body which zone is migrated and what debt remains.

The hardcoded-debt rule is incremental: a migrated chrome phrase must not return as a raw literal (see `ui/scripts/check-i18n-catalogs.mjs`). We do **not** fail CI on every remaining string in the app.

## PR review checklist

- [ ] Both catalogs have the same keys
- [ ] New copy uses semantic keys and interpolation
- [ ] No IDs, routes or capability names in catalogs
- [ ] Language selector still keyboard-accessible if Settings changed
- [ ] `npm test`, lint, `tsc`/build still green
- [ ] Boy scout limited to the files this PR already needed
