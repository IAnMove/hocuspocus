---
name: api-maestro-next-git
description: Automate Maestro workflows through its HTTP API and browser-based 3D compositor.
---

# Maestro API

## Clients

Use `clients/series_episode.py` for the recover-plan-apply-render workflow. Pass the reachable base URL discovered at runtime with `--base-url`; pass workspace, series, episode, and job IDs per invocation.

Use `clients/browser_cdp.mjs` when a workflow begins in the browser, notably Scene Animator canvas recording. Pass a separately launched Chromium debugging URL and the selected Maestro page URL at runtime. Use `--expression` or `--script` for page operations and `--screenshot` for visual verification. Scene Animator captures WebM internally, then `/api/v1/scenes/recordings` finalizes H.264 MP4 and publishes it in Videos with prompt, recipe, scene, and asset metadata.

## Operations

- `prepare-from-job`: copy durable outline/script stages from a recoverable planning job into the current episode and set its target duration through the episode API.
- `start-plan`: start one planning scope such as `shots` or `complete`.
- `plan-status` / `apply-plan`: inspect and apply a completed planning proposal.
- `start-render` / `render-status`: queue unapproved Series shots and inspect the durable render job.
- `episode` / `project`: inspect the current authoritative saved state.
- `set-status`: persist a verified episode lifecycle state after an external recovery or audit.
- Browser CDP evaluation and screenshots for Scene Animator preview/recording. Browser `MediaRecorder` performs the capture; the scene-recordings API converts and publishes the final MP4.

## Runtime Inputs

- A caller-reachable Maestro base URL.
- For browser-only operations, a caller-reachable Chromium debugging URL and Maestro page URL.
- Workspace name plus stable Series Lab project and episode IDs.
- A source planning job ID only when recovering completed stages.

## Outputs

Every operation prints one JSON response to stdout. Planning and render starts return durable job IDs that can be polled after process or app restarts.

## Notes

The server keeps canon snapshots immutable when an episode is saved. Applying a planning job performs its own stale-episode guard, so do not edit the episode between `start-plan` and `apply-plan`.
