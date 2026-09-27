# Optional example collections

Example media is absent from the current Git tree and UI build. This saves about 1,501 MiB from each source checkout and another copy from each production UI build. Small collection guides remain under `docs/examples`.

## User behavior

- Installation, build, startup, library browsing and schematic previews never download example media.
- **Video 3D → Shot library → Templates** contains 32 reusable shot compositions that work with the user's own media. **Examples and variants** holds the remaining 256 authored looks. All 288 existing template IDs remain supported, including saved projects and recent shots.
- Select an example or collection, check the download size, then press **Download**. The size includes missing shared dependencies, counted once. Progress and cancellation are available. Completed collections remain installed when another download is cancelled or fails.
- Saved scenes referencing missing `/examples/...` resources offer the same download controls in the editor. After completion, the current scene reloads its media. Users can also replace these resources with their own files.
- Only an explicit install POST starts network transfers. GET and HEAD never fetch external content. Missing media returns 409 with installation instructions; unknown paths return 404.
- Downloaded resources work offline, including video range requests and installed gallery pages. Gallery links to other collections may require installing those separately.
- Cache location: `app/cache/examples/`. Stop the app and remove this directory to reclaim optional media. Workspaces and model folders are unaffected.
- Vite development mode proxies `/examples` to the backend, like `/api`.

## Source and integrity

The [optional resource release](https://github.com/IAnMove/hocuspocus/releases/tag/example-assets-v1) hosts 19 ZIP collections outside Git. This resource prerelease does not replace the latest application release. It preserves the original media quality; ZIP compression is not a promise of smaller video files.

`app/resources/example_assets.json` pins archive URLs, sizes and SHA-256 checksums, file checksums, and dependencies. Its `revision` records the original source snapshot. Runtime downloads use release assets, not historical Git blobs.

The installer bounds each transfer, verifies the complete archive and every file, rejects unexpected paths or duplicate entries, and stages content before publishing it. Paths inside ZIPs never become extraction paths: storage uses flat content-addressed filenames. Partial downloads are cleaned up. Corrupt cached content is detected and can be downloaded again. One collection job runs at a time per application process.

API:

- `GET /api/v1/examples`: collection availability, required download sizes and current job.
- `POST /api/v1/examples/install`, JSON `{"collections":["creative"]}` and header `X-Hocus-Action: install-examples`: start an explicit download; returns 202. Unknown collections return 422; a running job returns 409.
- `DELETE /api/v1/examples/install/{job_id}` with the same header: request cancellation. A pending network read may take up to its 30-second timeout to settle.
- `GET /examples/{path}`: serve verified installed content only.

The HTML and scripts in gallery packages come from the same recorded repository snapshot as their media.

## Source tree versus Git history

Deleting files does **not** erase historical blobs. A full `git clone` can still download old media. No history rewrite or force-push is included.

After this change reaches the installed branch, a lightweight fresh checkout can use:

```sh
git clone --depth 1 --single-branch --branch main https://github.com/IAnMove/hocuspocus.git
```

The upstream Pinokio Download flow already runs `git clone --depth 1 --single-branch` in `prepareLauncherDownload` and `cloneLauncherRemoteRepo` ([source](https://github.com/pinokiocomputer/pinokiod/blob/add4a674ad1ba95bb62ec427fce519fe5bf0e9bf/server/index.js#L9374)). Other paths, including `script.download` and checkpoint installation, still use a full clone. This was verified in upstream source, not on the user's installed macOS version. Check a specific installation with `git rev-parse --is-shallow-repository`; `true` confirms shallow history. Existing full clones are not automatically shrunk by updating.

A source ZIP of the new revision also excludes history. Pinokio clones this repository before `install.js`, so that script cannot reduce the initial transfer. Deleting old branches does not remove blobs reachable from `main`. Any future history migration must separately coordinate branches, open PRs and existing clones; the independent resource release must be retained.

## Maintaining the catalog

Do not add examples back to `ui/public/examples/`; it is ignored. Media-generation scripts may write there locally, but that folder is not a distribution input. Keep the manifest and integrity tests in Git.

To create a new resource version from media matching the manifest:

```sh
python scripts/package_example_assets.py \
  --source /path/to/archived/examples \
  --output /path/outside/repository/collections \
  --manifest app/resources/example_assets.json \
  --release-base https://github.com/IAnMove/hocuspocus/releases/download/example-assets-v2
```

The builder validates input checksums and records cross-collection file references. Publish all resulting ZIPs plus a copy of the manifest, verify the release sizes/checksums and test an actual download before shipping the updated manifest. Never overwrite assets belonging to an existing version.

`templateCatalog.ts` selects core templates by distinct shot purpose, camera movement or layout; illustrated variants stay in the examples view. Adding a core template requires keeping it free of optional-media references. Do not remove legacy IDs merely to simplify the visible catalog.

The tiny TV-head GLB in `ui/tests/fixtures` is an offline renderer test fixture, not shipped UI content. Export E2E tests supply their own media and never depend on optional examples.
