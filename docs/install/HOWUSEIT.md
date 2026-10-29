# HOWUSEIT — Settings > Installation

Operator guide for **optional engines after the base install**. The studio,
editors, Director, Wizard and local WanGP generation (including native MiniMax
H3) are always installed. Everything else is a catalog component you add,
update or remove from the running app.

UI: **Settings → Installation** (`ui/src/components/Installation`). Server:
`app/services/install_manager.py` behind `GET /api/v1/system/install`,
`POST .../{id}/install`, `POST .../{id}/uninstall` and
`GET .../{id}/output`, mounted by `create_system_capabilities_router`
(core runtime included). Catalog:
`app/runtime/install_catalog.json` — the Pinokio first-install dialog, the
Advanced menu and this tab all read the same file.

Related: [runtime recipes](../development/RUNTIME_PROFILES.md),
[FLUX 3 / Drama 3](../generation/FLUX3_DRAMA3.md),
[TRELLIS.2](../development/TRELLIS2.md). The in-app **Storage Manager**
(opened from this tab) deletes downloaded weights; it is a different surface.

---

## 1. What this system is

| Surface | When to use it |
|---|---|
| Pinokio **Choose what to install** | First Install. Offers only extras this computer can run and has not installed. Unticked means “not now”. Skipped when nothing is left to offer. |
| **Settings → Installation** | Add, update or remove one extra while HocusPocus is running. Shows state, measured size and what a removal really frees. |
| Pinokio **Advanced** menu | Same scripts as the tab (`<id>_install.js`). Use it when the tab cannot start Pinokio (`pterm` missing, or a checkout outside `<pinokio>/api/`). |
| **Storage Manager** | Downloaded model weights, LoRAs and generated media. Uninstall never deletes those. |

Use the tab when you already have the studio and want FLUX 3, Hunyuan, TRELLIS,
SAM, UniRig or H3 Legacy. Use Pinokio **Update** to repair the **base**
install (`app/env`). The tab’s base row is read-only.

Installing is **not** offered to MCP or the Wizard: it downloads gigabytes, so
a person starts it from the tab or the Advanced menu.

---

## 2. Catalog (ids, sizes, restart)

Sizes are `estimatedGiB` from `install_catalog.json`, stored as
`estimatedGiB * 1024³` bytes. The UI prints them with `formatBytes` as
`N.N GB` (GiB). They are estimates for a missing install; an installed
row shows the measured folder size instead.

| id | Title | Est. | Restart after install | Isolated env (removed with the extra) |
|---|---|---|---|---|
| `creation_models` | FLUX 3 / Drama 3 | 6 GB | No | `app/services/creation_models/env` (+ vendor, input, output, extra_model_paths) |
| `hunyuan3d` | 3D generation (Hunyuan3D) | 10 GB | Yes | `app/services/hunyuan3d/env` + vendor |
| `trellis2` | TRELLIS.2 | 13 GB | Yes | `app/services/model3d_runtimes/trellis2/env` + vendor |
| `sam` | Inpaint masks (SAM 3.1) | 7 GB | No | `app/services/sam/env` + `sam3` |
| `rigging` | AI rigging (UniRig) | 11 GB | Yes | `app/services/rigging/env` + vendor |
| `minimax_h3` | MiniMax H3 Legacy (ComfyUI) | 6.5 GB | No | `app/services/minimax_h3/env` + vendor |

Base (always installed): about **11 GB** in `app/env`. Native H3 lives there.
H3 Legacy is optional and no longer part of a fresh Install.

Hardware gates come from `runtime_profiles.detect_profiles`. An unsupported
row is `unsupported` with the engine’s `reason` (for example “needs more
VRAM”). The first-install dialog does not list it. The tab shows it but
offers no Install/Remove.

---

## 3. Hard limits

1. **One change at a time.** A second Install/Remove returns `409`
   `install_in_progress` (“Another change is running: {kind} {component}.”).
   Jobs persist in `app/.runtime/install-jobs/<id>.json`.
2. **Install needs Pinokio.** `pterm start <id>_install.js --ref
   pinokio://127.0.0.1:42000/api/<folder>` runs detached; output goes to
   `app/.runtime/install-jobs/<id>.log`. `pterm` always exits 0; success is
   “is it installed afterwards?”, never the exit code. Without `pterm`, or
   when the checkout is not under `<pinokio>/api/` (unless
   `HOCUS_PINOKIO_REF` is set), Install is disabled. Remove still works.
   `HOCUS_PINOKIO_PORT` overrides `42000`.
3. **Keep HocusPocus open during Install.** Stopping or restarting can
   interrupt it: Pinokio ends the app’s child processes. After a server
   restart a job whose `pterm` client has vanished is closed from the
   installed state (`not_installed_after_run` if nothing landed).
4. **Uninstall deletes only catalog `remove` paths** under `app/services`,
   plus `app/.runtime/<engine>.managed`. Model checkpoints stay. A symlink
   (a shared environment) is `409` `shared_environment`. An engine that is
   running is `409` `in_use`. Today only H3 Legacy reports “running”
   (`minimax_h3_service.is_runtime_running`); the core runtime has no H3
   websocket client and treats it as not in use.
5. **Folder size ≠ freed space.** uv hard-links packages into Pinokio’s
   shared cache. `reclaimableBytes` counts only files with a single link
   across every folder the removal deletes. The confirm button says that
   number. When it is less than half the folder, the row explains that
   Pinokio’s Disk Saver can reclaim the rest.
6. **Low disk is a warning, not a lock.** If `estimatedBytes > freeBytes`
   the row warns; Install still starts. Profiles are cached 15 s; folder
   sizes 300 s (`None` / “measuring…” until the background walk finishes).
7. **Unsupported hardware cannot be forced** from the tab (`409`
   `unsupported` with the profile reason). Unknown components are `404`
   `unknown_component`.

---

## 4. Operator workflow

1. Open **Settings → Installation**.
2. Read free disk space and each row’s state:
   `installed`, `needs_update`, `not_installed`, `running`, `unsupported`.
3. **Install** or **Update** on a supported, idle row. Update is the same
   Pinokio script as Install; it appears when the environment folder exists
   but the receipt is stale.
4. Watch the live installer output. Leave the app running.
5. On success: “Installed and ready to use.” or “Installed. Restart
   HocusPocus to use it.” (Hunyuan, TRELLIS, UniRig). The success notice
   stays 30 minutes; a failure stays until the next attempt.
6. **Remove** is two clicks (4 s confirm window). The second click names
   the reclaimable size. Then use **Storage Manager** if you also want the
   weights gone.

First Install in Pinokio: tick only the extras you want now. You can add the
rest later from this tab. A computer that only gets the **core** runtime
(no NVIDIA / pre-Turing / ARM / Apple Silicon) is not offered extras it
cannot run.

---

## 5. HTTP surface

`workspace` is not involved. These routes are process-local.

```bash
# Status: launcher, disk, base row, every component.
curl "$BASE/api/v1/system/install"

# Start (202). Same path for Update; the server re-runs the component script.
curl -X POST "$BASE/api/v1/system/install/sam/install"

# Last 60 log lines (1–400). ANSI and progress-bar redraws are stripped.
curl "$BASE/api/v1/system/install/sam/output?lines=60"

# Remove (202). Does not delete checkpoints.
curl -X POST "$BASE/api/v1/system/install/sam/uninstall"
```

```javascript
const status = await fetch(`${BASE}/api/v1/system/install`).then(r => r.json());
// status.launcher.available, status.disk.freeBytes, status.busy,
// status.components[].state / sizeBytes / reclaimableBytes / restartRequired
const job = await fetch(`${BASE}/api/v1/system/install/creation_models/install`, {
  method: 'POST',
}).then(async r => {
  if (!r.ok) throw await r.json();
  return r.json();
});
// { component, kind: "install"|"uninstall", state: "running", startedAt, finishedAt, code, message, pid }
```

Refusals use `{ "detail": { "code", "message" } }`:

| HTTP | code | When |
|---|---|---|
| 404 | `unknown_component` | id not in the catalog |
| 409 | `unsupported` | profile says this machine cannot run it |
| 409 | `install_in_progress` | another component is busy |
| 409 | `launcher_unavailable` | no `pterm` / not a Pinokio checkout |
| 409 | `in_use` | H3 Legacy sidecar is up |
| 409 | `shared_environment` | a `remove` path is a symlink |
| 409 | `outside_app` | a `remove` path escaped `app/services` (should not happen with the catalog) |
| 422 | — | `output?lines=` outside 1–400 |

A finished job may carry `not_installed_after_run`, `interrupted` (removal
cut off; run Remove again) or `removal_failed`.

---

## 6. Pitfalls

- **Removing SAM listed 7 GB and freed ~0.3 GB.** That is the hard-link
  cache, not a bug. Believe the confirm size, then Disk Saver if you need
  the shared wheels gone.
- **Weights survive Remove.** FLUX/Drama stay under
  `app/ckpts/creation_models/`; Hunyuan/TRELLIS under `app/ckpts/model3d`
  and `app/services/model3d_runtimes` weights; SAM checkpoints under
  `app/services/sam/checkpoints`. Storage Manager is the delete path.
- **TRELLIS Install is only the runtime.** Weights still need
  **Settings → Model Visibility → 3D → download**, Hugging Face access to
  DINOv3 and RMBG-2.0, and Linux NVIDIA ≥ 24 GB. See
  [TRELLIS2.md](../development/TRELLIS2.md).
- **FLUX still needs `HF_TOKEN`** on this Pinokio app after Install. See
  [FLUX3_DRAMA3.md](../generation/FLUX3_DRAMA3.md).
- **Hunyuan on Windows** still needs VS Build Tools (v142/v143) and CUDA
  12.8. Retry Install after fixing the toolchain; Reset is unnecessary.
- **decord 0.6.0 on Linux.** A fresh WanGP or SAM install used to die at
  `uv pip check` (“built for a different platform”). Setup now rewrites
  that one known wheel tag after `decord` imports, on Linux x86_64 only.
  Existing receipts are not invalidated.
- **A development worktree** is `not_in_pinokio`. Point
  `HOCUS_PINOKIO_REF` at the real app, or use the Advanced menu from the
  Pinokio checkout.
- **Core-only machines.** The tab lists extras as `unsupported` instead of
  offering a download that would be skipped. Do not expect Hunyuan or
  TRELLIS buttons to work there.

Recipe fingerprints, conda isolation and Reset live in
[RUNTIME_PROFILES.md](../development/RUNTIME_PROFILES.md). Do not edit
`defaultInstall` on H3 Legacy in `profiles.json` to hide it: that field is
part of the install fingerprint and would force a ~6 GB reinstall. The
catalog is the policy.
