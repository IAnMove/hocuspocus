# HocusPocus UI

This directory contains the React 19, TypeScript, Tailwind CSS and Zustand
frontend for HocusPocus. It is built into `ui/dist` and served by the
FastAPI application; it is not a separate production service.

HocusPocus is an experimental, non-commercial fork of
[Blizaine/Maestro](https://github.com/Blizaine/Maestro), which in turn builds
on [Wan2GP](https://github.com/deepbeepmeep/Wan2GP). See the
[project README](../README.md) and [license summary](../LICENSE) before using
or redistributing it.

## Requirements

- Node.js 20, matching CI.
- npm and the committed `package-lock.json`.
- For live API calls, a HocusPocus backend running at
  `http://127.0.0.1:7860` (the Vite development proxy target).

The normal Pinokio **Install**, **Start** and **Update** actions manage these
steps for end users. The commands below are for frontend development.

## Development

Run all commands from this `ui` directory:

```bash
npm ci
npm run dev
```

Vite serves the development UI at `http://127.0.0.1:3000` and proxies `/api`
and `/classic` to `http://127.0.0.1:7860`. Start the backend from the project
root with Pinokio or with its existing Python environment:

```bash
app/env/bin/python app/launch.py
```

## Quality checks

```bash
npm run test
npm run lint -- --max-warnings=0
npm run build
npm run budget
```

`npm run check` runs the same test, lint, type-check/build and bundle-budget
sequence used by CI. The build output is `ui/dist`; do not edit it manually.

## Architecture

- `src/api/client.ts` is the typed HTTP boundary. Browser code should use it
  instead of creating feature-specific URL conventions. Slice modules live
  beside it and are reexported from `client.ts`.
- `src/stores/useStore.ts` is the public Zustand facade. Extracted reducers
  and slices live beside it and must preserve that facade for existing views.
- `src/features/` owns large workflows such as Series Lab, Story Lab and the
  video editor.
- `src/components/` contains reusable application and navigation UI.
- `src/i18n/` is the English/Spanish catalog and language preference. See
  [internationalization](../docs/development/INTERNATIONALIZATION.md).
- `tests/` uses Node's test runner, jsdom and Testing Library for behavioural
  regression tests.
- `scripts/check-build-budget.mjs` prevents accidental growth of the entry
  bundle and verifies that heavy overlays remain lazy-loaded.

The browser uses same-origin `/api/v1/...` routes in production. Authentication
for an explicitly shared LAN server is supplied by the application session;
do not store provider keys or bearer tokens in frontend source or fixtures.

## Adding a change

1. Put feature code in the owning feature directory and keep API calls in
   `src/api/client.ts`.
2. Add a behavioural regression test under `tests/`.
3. Run `npm run check`.
4. If an API contract changes, update its backend Pydantic contract and the
   generated/checked TypeScript contract in the same change.

For application setup, API examples in JavaScript, Python and curl, model
notes and troubleshooting, use the [root documentation](../README.md).
