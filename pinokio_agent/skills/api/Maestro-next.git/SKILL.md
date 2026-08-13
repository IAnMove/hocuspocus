---
name: api-maestro-next-git
description: Automate recoverable Series Lab episode planning and rendering through Maestro's HTTP API.
---

# Maestro Series Lab API

## Clients

Use `clients/series_episode.py` for the recover-plan-apply-render workflow. Pass the reachable base URL discovered at runtime with `--base-url`; pass workspace, series, episode, and job IDs per invocation.

## Operations

- `prepare-from-job`: copy durable outline/script stages from a recoverable planning job into the current episode and set its target duration through the episode API.
- `start-plan`: start one planning scope such as `shots` or `complete`.
- `plan-status` / `apply-plan`: inspect and apply a completed planning proposal.
- `start-render` / `render-status`: queue unapproved Series shots and inspect the durable render job.
- `episode` / `project`: inspect the current authoritative saved state.
- `set-status`: persist a verified episode lifecycle state after an external recovery or audit.

## Runtime Inputs

- A caller-reachable Maestro base URL.
- Workspace name plus stable Series Lab project and episode IDs.
- A source planning job ID only when recovering completed stages.

## Outputs

Every operation prints one JSON response to stdout. Planning and render starts return durable job IDs that can be polled after process or app restarts.

## Notes

The server keeps canon snapshots immutable when an episode is saved. Applying a planning job performs its own stale-episode guard, so do not edit the episode between `start-plan` and `apply-plan`.
