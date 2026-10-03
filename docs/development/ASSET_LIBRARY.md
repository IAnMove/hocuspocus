# Asset library (contract)

Optional library of free assets: HDRI, PBR materials, LUTs, humanoid animations, sound effects and models. This page covers
the contract (phase 3.F1 of the local-quality roadmap, `docs/development/calidad-local/03-biblioteca-cc0.md`). Curation,
packaging, the in-app browser, the consumers and the credits are later phases.

## Rules

- **Optional.** Nothing is downloaded at startup or when the catalog is listed. A collection is installed only when the user
  asks, like the optional examples (`docs/development/OPTIONAL_EXAMPLES.md`).
- **Licensed.** Every file in the catalog carries `license`, `source`, `source_url` (https), `author` and `retrieved_at`
  (`YYYY-MM-DD`). A manifest with a file missing any of them does not load, and a test fails. For now only `CC0-1.0` is
  accepted (`services.asset_library.LICENSES`); accepting CC-BY, which requires credit, is the user's decision.
- **Verified.** The pinned manifest lists the size and SHA-256 of every file and of every collection archive. Files are
  published only when both match, and they are checked again when read.

## Catalog

The pinned manifest is `app/resources/asset_library.json`, and its schema is
[`asset-library-v1.schema.json`](asset-library-v1.schema.json). It starts empty (revision 1).

```json
{
  "schema": "hocuspocus.asset-library",
  "revision": 1,
  "files": {
    "studio/studio_small_08_1k.hdr": {
      "kind": "hdri", "size": 1572864, "sha256": "…", "collection": "hdri-starter",
      "license": "CC0-1.0", "source": "polyhaven", "source_url": "https://polyhaven.com/a/studio_small_08",
      "author": "Sergej Majboroda", "retrieved_at": "2026-10-03"
    }
  },
  "collections": {
    "hdri-starter": {
      "title": "Starter HDRIs", "files": ["studio/studio_small_08_1k.hdr"], "dependencies": [], "size": 1572864,
      "archive": {"url": "https://github.com/IAnMove/hocuspocus/releases/download/library-v1/hdri-starter.zip",
                  "size": 1500000, "sha256": "…"}
    }
  }
}
```

### Kinds

Kinds and their extensions are declared once, in `app/services/media_kinds.py`:

| Kind | Extensions |
|---|---|
| `hdri` | `.hdr`, `.exr` |
| `material` | `.png`, `.jpg`, `.jpeg`, `.webp`, `.exr`, `.json` |
| `lut` | `.cube` |
| `animation` | `.glb`, `.bvh` |
| `sfx` | `.wav`, `.ogg`, `.flac`, `.mp3` |
| `model3d` | `.glb`, `.gltf` |

The asset manifest also knows `hdri`, `material` and `lut` now, so `.hdr`/`.exr` infer to `hdri` and `.cube` to `lut`.
The older extension sets were left as they were. They already disagree, and this change does not touch them:

| Module | Audio | Models |
|---|---|---|
| `core_workspace` | `.wav`, `.mp3` | `.glb`, `.gltf`, `.obj`, `.ply`, `.stl`, `.usdz`, `.zip` |
| `media_paths` | ten extensions | `.glb` |

`asset_catalog.MEDIA_EXTENSIONS` (the workspace listing) still leaves out `.hdr`, `.exr`, `.cube` and `.bvh`.

### Collections

The rules for a collection:

- The id is lowercase words joined by hyphens.
- `files` lists each file exactly once, and every file belongs to exactly one collection.
- `size` is the sum of the file sizes.
- `dependencies` may only name other collections.
- `archive.url` must be https on `github.com` or its release storage hosts.

## Cache

The cache is content-addressed: `app/cache/library/<sha256><ext>`. The install receipt is
`app/cache/library/<collection>.installed.json`. Archive paths never become disk paths.

## Routes

| Route | What it does |
|---|---|
| `GET /api/v1/library` | Lists the collections with their size, download size, installed state, `kinds`, `licenses` and `sources`. Also lists `items` (every file of an installed collection, with its license and its `url`) and the current `job`. It never downloads. |
| `POST /api/v1/library/install` | Installs `{"collections": [...]}`. Requires the header `X-Hocus-Action: install-library`. Only one job runs at a time; a second one answers 409. |
| `DELETE /api/v1/library/install/{job_id}` | Cancels the job. Requires the same header. |
| `GET` and `HEAD /api/v1/library/files/<sha256><ext>` | Serves an installed file as immutable. Answers 409 if its collection is not installed and 404 if the name is unknown. |

Using a library file in a workspace writes its sidecar with `execution.mode: "import"` and `origin.license`
(`AssetLibrary.license_for(name)`, `build_asset_manifest(license=...)`). The asset manifest schema has the `origin.license`
block: `spdx`, `source`, `source_url`, `author` and `retrieved_at`.

## Secure downloads

`app/services/secure_download.py` is the one downloader for remote catalogs. The asset library, the optional examples
(`example_collections.py`) and the community templates (`template_community.py`) all use it. It enforces:

- `https://` only, with no credentials in the URL, to the hosts each caller allows;
- redirects only to another allowed https host;
- a read takes at most `limit + 1` bytes;
- downloads with a known size must match their size and SHA-256 exactly, and can be cancelled.

Hosts each caller allows:

- **Asset library and examples:** `github.com`, `objects.githubusercontent.com` and
  `release-assets.githubusercontent.com`.
- **Community templates:** the index host and `raw.githubusercontent.com`.

Before this change, `urlopen` followed redirects to any host. Now a redirect outside those hosts fails.

## Coordination with the template library

The paused template plan (`docs/development/TEMPLATE_LIBRARY_PLAN_2026-09-28.md`, draft PR #532) foresees packs of
effects, titles and fonts in its own index, with a `kind`. Those packs stay in that plan. This library uses the same idea
of a `kind` per entry, with the kinds above, so a later shared index can merge both without renaming anything.
