# Scene templates you can share (`.hptemplate`)

Anyone can turn a Video 3D or Video 2D scene into a reusable template, keep it in
the local **template library**, export it as a file, import someone else's and
(later) publish it on the community site. People and agents use the same library
through HTTP and the MCP `templates.*` commands.

Code: `app/services/template_format.py`, `app/services/template_library.py`,
`app/services/template_commands.py`, `app/routers/templates.py`.
Plan and roadmap: [TEMPLATE_LIBRARY_PLAN](../development/TEMPLATE_LIBRARY_PLAN_2026-09-28.md).

## In the app

**Video 3D → Change shot → My templates**: save the current shot as a template
(name, tags, author and X handle, license, sample files or empty slots, adjustable
duration; the current frame becomes its preview), click a template to apply it
(sample media are copied into the workspace; *Keep assets* keeps your current
characters), download it as `.hptemplate` or import one after reviewing what it
contains.

**Video 2D → My templates** (Scene Animator side panel) does the same for 2D scenes:
slots are image/video layers with workspace media, the preview is the current frame
and using a template opens it in the animator. Save the scene first if it still has
local (unsaved) files: templates only reference workspace or example media.

## What a template is

* **Slots**: what the person must provide (a character GLB, a background image…).
  Video 3D slots target a scene slot (`subject_1`, `subject_2`, `background`, `prop`);
  Video 2D slots target a layer id. Without declared slots, every scene slot (3D) or
  every image/video layer with workspace media (2D) becomes one.
* **Controls**: values worth tuning, each a JSON Pointer into the document
  (`/duration`, `/camera/fov`, `/texts/0/text`) with a type (`number`, `text`, `color`,
  `boolean`, `choice`), limits and a default.
* **Metadata**: `id` (`author/slug`), title, description, tags, author (name, X handle,
  https link), license (`CC0-1.0`, `CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`, `MIT`,
  `all-rights-reserved`), template version and required format/app version.

## File format

`.hptemplate` is a zip: `template.json` (manifest, `kind: "hocuspocus.template"`,
`version: 1`), `document.json`, optional `preview.png|jpg|webp` (≤ 2 MB) and optional
sample media `media/<sha256>.<ext>`. Limits: 64 MB zip, 64 media files, 2 MB documents.
Only data: no scripts, no absolute paths, no `..`, no symlinks, no external URLs.
Media whose bytes do not match their SHA-256 name are dropped, and a document that
references missing media is refused.

By default a template is saved **without media**: slot media (the model/image,
speech, screen and 2D frame sequence) are emptied; Video 3D soundtrack and world
SFX files and Video 2D audio tracks are removed (they cannot be slots); any other
workspace media must be declared as a slot (`unbound_media`). `include_media: true`
packs every workspace file the scene uses.
Files under `/examples/` are always kept as references.

Importing an old Video 3D `*.world3d.template.json` converts it (media removed).

## Applying

`templates.apply` returns a ready document: slots filled with workspace or example
files, controls set and the template's sample media copied into the workspace as
`tpl-<hash>.<ext>`. It never saves: pass the document to `scenes.document.save`,
`scenes.world3d.export` or `scenes.video2d.export`. `missingSlots` lists required
slots that are still empty.

## HTTP and MCP

| MCP | HTTP |
|---|---|
| `templates.list` `{editor?, tag?, query?}` | `GET /api/v1/templates?editor=&tag=&q=` |
| `templates.get` `{id}` | `GET /api/v1/templates/{author}/{slug}` |
| `templates.save` `{workspace, editor, document, title, …, include_media?, preview?, expected_updated_at?}` (`preview`: workspace image or `data:image/…;base64`) | `POST /api/v1/templates` |
| `templates.apply` `{id, workspace, slots?, controls?}` | `POST /api/v1/templates/{author}/{slug}/apply` |
| `templates.export` `{id, workspace}` (writes the file into the workspace) | `GET /api/v1/templates/{author}/{slug}/package` |
| `templates.preflight` `{workspace, file}` | `POST /api/v1/templates/preflight` (file as body) |
| `templates.import` `{workspace, file, replace?}` | `POST /api/v1/templates/import?replace=` (file as body) |
| `templates.delete` `{id}` | `DELETE /api/v1/templates/{author}/{slug}` |

Also `GET /api/v1/templates/{author}/{slug}/preview` and `/media/{name}`.
Saving an existing id needs `expected_updated_at` (compare-and-swap); importing one
needs `replace`.

## Storage

`HOCUS_TEMPLATE_LIBRARY_DIR`, or `$PINOKIO_HOME/cache/maestro/template-library`: one
folder per id with the package members plus `origin.json` (`user`, `imported` or
`community`). Templates saved in the browser by older versions are not read.
