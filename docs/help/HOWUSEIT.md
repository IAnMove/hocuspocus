# HOWUSEIT — In-app Help tutorial

Maintainer guide for the **How to use HocusPocus** overlay. This is the
in-product tour, not a second copy of README and not a Wizard capability.

UI: top gallery chrome **Help** button (`aria-label` from `help:openAria`).
Code: `ui/src/components/Help/HelpOverlay.tsx`, lazy wrapper in `ui/src/App.tsx`.
Copy: `ui/src/i18n/locales/{en,es}/help.json`. Stills: `ui/public/help/`.

Related: [operator index](../HOWUSEIT.md), [APP_USER_GUIDE](../APP_USER_GUIDE.md),
[Tijeral](../cut-paper/HOWUSEIT.md).

---

## 1. What this system is

A modal with a table of contents, ES/EN switch, and screenshots of the current
layout. Opening it does not start a GPU job, change the output folder, or
write settings other than the shared UI language.

| Piece | Behavior |
|---|---|
| Opener | `window.dispatchEvent(new Event('hocuspocus:help-open'))` from `TabFilter` |
| Bundle | The overlay is `lazy()`-loaded. The chunk is fetched on first open only |
| Language | The `<select>` calls `setUiLanguage`. That is the app language, not a local draft |
| Close | Overlay click, Escape, or the close button. Focus returns to the opener |

Use Help when an operator needs the **current chrome** (Direct generation in
the large pane, Wizard rail, Studios vs Production). Use the HOWUSEIT pages
when they need HTTP contracts, limits, or worker paths.

---

## 2. Hard limits

1. **On demand.** `LazyHelpOverlay` renders `null` until the first open event.
   Do not assume the dialog exists in the initial DOM.
2. **One copy source.** Visible titles and bodies come from the `help`
   namespace. Do not hardcode section prose in the component.
3. **Shared language.** Switching ES/EN inside Help changes the whole UI
   language. It does not rewrite Story Lab spoken language or filenames.
4. **Layout-bound stills.** Images under `/help/*.jpg` must match the current
   chrome. A stale screenshot is worse than no screenshot.
5. **Tijeral reuses Story Lab art.** The `tijeral` section points at
   `/help/story-lab.jpg` on purpose. Do not invent a fake Tijeral tab image.
6. **No GPU, no network job.** Help is static public assets plus i18n JSON.

---

## 3. Sections (keep this list in sync)

`SECTIONS` in `HelpOverlay.tsx` is the authority. Each id needs `nav.<id>`,
`<id>.title`, and `<id>.body` in both locale files.

| id | Nav (EN) | Image |
|---|---|---|
| `start` | Layout | `/help/direct-image.jpg` |
| `wizard` | Wizard | `/help/wizard.jpg` |
| `direct` | Direct generation | `/help/direct-video.jpg` |
| `queue` | Queue | `/help/activity.jpg` |
| `studios` | Studios | `/help/story-lab.jpg` |
| `faces` | Talking faces | `/help/character-creator.jpg` |
| `tijeral` | Cut-paper | `/help/story-lab.jpg` (shared) |
| `video3d` | Video 3D | `/help/video-3d.jpg` |
| `production` | Production | `/help/director.jpg` |
| `media` | Library | `/help/media.jpg` |
| `settings` | Settings | `/help/settings.jpg` |
| `examples` | Example outputs | `/help/example-image.jpg` + `example-video.jpg` |

`examples` has no `image` field; the component renders the two stills in a
grid. Bodies may contain `\n\n` — the overlay splits them into paragraphs.

---

## 4. How to add or fix a section

1. Add `{ id, image?, imageKey? }` to `SECTIONS`.
2. Add matching keys to **both** `en/help.json` and `es/help.json`.
3. Drop a JPG in `ui/public/help/` and an `images.<imageKey>` alt string.
4. Update `ui/tests/helpOverlay.test.tsx` if the heading text changes.
5. Run the Help e2e if chrome, focus, or language switching changed:

```sh
cd ui
npm run i18n:check
npm run test -- tests/helpOverlay.test.tsx
npm run test:e2e -- help
```

The e2e covers 1280×720 and 390×844: keyboard open, language combo focus,
in-viewport images (`complete` and `naturalWidth > 0`), hash-nav to Example
outputs, ES switch, Escape, and focus restore. It does not prove the
screenshots still match production chrome — that is a visual check.

---

## 5. Pitfalls

- Duplicating Help prose into README. Point at the overlay or a HOWUSEIT page.
- Adding a section in English only. `i18n:check` fails the PR.
- Treating the language combo as Help-only. It is `setUiLanguage`.
- Documenting a “Tijeral studio.” The loader is a Story Lab library button.
  See [cut-paper HOWUSEIT](../cut-paper/HOWUSEIT.md).
- Importing HelpOverlay from a hot path. Keep the lazy wrapper so the tour
  JS/CSS stays off the first paint.

---

## 6. Files to read next

| Path | Why |
|---|---|
| `ui/src/components/Help/HelpOverlay.tsx` | Section table and modal |
| `ui/src/App.tsx` | `hocuspocus:help-open` listener |
| `ui/src/components/MainContent/TabFilter.tsx` | Help button |
| `ui/src/i18n/locales/en/help.json` | English copy |
| `ui/tests/helpOverlay.test.tsx` | Render and section contract |
| `ui/e2e/specs/help.spec.ts` | Keyboard, i18n, viewports |
