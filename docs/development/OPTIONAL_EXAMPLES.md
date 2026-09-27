# Optional example media

Example media is no longer stored in the current Git tree or copied into the UI build. The removal saves about 1,501 MiB from each source checkout and another copy from each production UI build. Small collection guides remain under `docs/examples`.

## User behavior

- Installation, UI build and server startup do not download any example media.
- `/examples/...` URLs used by saved projects, templates and gallery pages continue to work. The backend downloads only the requested file on first use, then serves its cached copy, including video range requests.
- Opening a preview can download its image; using a scene can download its referenced images, video or audio. Opening a complete gallery can load several previews. Full exported movies and archives are downloaded only when requested.
- The first use requires internet access to GitHub. An unavailable or invalid download returns 503 and can be retried. Verified cached resources work offline.
- Cache location: `app/cache/examples/`. Stop the app and remove this directory to reclaim all optional media. Nothing in workspaces or model folders is touched.
- Vite development mode proxies `/examples` to the backend, like `/api`.

## Source and integrity

`app/resources/example_assets.json` pins the public repository revision and lists the size and SHA-256 of every allowed file. Resources currently come from the immutable archived revision on `raw.githubusercontent.com/IAnMove/hocuspocus`. This needs no new release, account or upload. It is a transitional host: keep that revision accessible until a dedicated asset release/store replaces it.

Requests cannot select arbitrary network locations or filesystem paths. Downloads are bounded by the declared size, hashed, written to temporary files and atomically published. Concurrent requests for the same file share the completed result; partial or corrupt files are never served. HEAD requests only return manifest metadata.

Example filenames are not cache paths: local storage is content-addressed. The manifest includes HTML and scripts for the existing review galleries as well as images and media. They come from the same pinned, reviewed repository snapshot.

## Important: source tree versus Git history

Deleting files in this PR does **not** erase their historical blobs. A normal full `git clone` can still download the old media. No history rewrite or force-push is included in this change.

After this change reaches the branch being installed, a lightweight fresh checkout can use:

```sh
git clone --depth 1 --single-branch --branch main https://github.com/IAnMove/hocuspocus.git
```

The current upstream Pinokio Download flow already runs `git clone --depth 1 --single-branch` in `prepareLauncherDownload` and `cloneLauncherRemoteRepo` ([source](https://github.com/pinokiocomputer/pinokiod/blob/add4a674ad1ba95bb62ec427fce519fe5bf0e9bf/server/index.js#L9374)). Other paths, including `script.download` and checkpoint installation, still use a full clone. This was verified in upstream source, not on the user's installed macOS version. Check a specific installation from its repository directory with `git rev-parse --is-shallow-repository`; `true` confirms it has a shallow history. A fresh clone through that shallow Download flow benefits once the example-removal change reaches the default branch. Existing full clones are not automatically shrunk by updating.

A source ZIP of that new revision also excludes historical files. The Pinokio repository clone happens before this application's `install.js`, so changing `install.js` cannot shrink that initial transfer. Distribution must use a shallow clone or a source archive, or the repository history must be migrated separately.

A future history cleanup must preserve the archived examples at an independent asset release/store **first**, update and verify the manifest's source, then coordinate rewritten branches, open PRs and existing clones. Do not delete the current pinned revision before migrating its media. Simply deleting old merged branches does not remove blobs reachable from `main`.

## Maintaining the catalog

Do not add large examples back to `ui/public/examples/`; the path is ignored. Development media-generation scripts may still write there locally, but those results are not distribution inputs. Publish a separately versioned asset collection and update its metadata deliberately. Keep the manifest and its integrity tests in Git.

The tiny TV-head GLB in `ui/tests/fixtures` is an offline renderer test fixture, not shipped UI content.
