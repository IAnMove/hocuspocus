# HocusPocus community templates

Scene templates made by the [HocusPocus](https://github.com/IAnMove/hocuspocus)
community. Browse them at **https://ianmove.github.io/hocuspocus-community/** or
from the **Community** tab of *My templates* inside HocusPocus (Video 3D and Video 2D).

Plantillas de escena hechas por la comunidad de HocusPocus. Míralas en la web o en
la pestaña **Comunidad** de *Mis plantillas* dentro de HocusPocus.

## Share yours / Comparte la tuya

1. In HocusPocus: **My templates → Save this shot/scene as a template** (name, tags,
   author, X handle, license), then **Download** the `.hptemplate` file.
2. Fork this repository and add it as `templates/<your-x-handle>/<slug>.hptemplate`
   — the path must match the template id shown in HocusPocus (`author/slug`).
3. Open a pull request. CI validates the package with the same code HocusPocus uses
   to import it; a maintainer reviews it and, once merged, it appears on the site
   and in the app.

Rules:

- Only share what you have the right to share, with a clear license.
- No images of real people without their consent; no hateful or sexual content.
- Templates are data only (scene JSON, preview and optional sample media). Anything
  else is rejected.
- Keep packages small (≤ 64 MB); prefer templates **without** sample media.

## How it works

`templates/` holds the packages. On every push to `main`, the workflow validates them
with `scripts/community_index.py` from the HocusPocus repository, writes
`index.json` (with each package's SHA-256), extracts previews and publishes the site
from `site/` to GitHub Pages. HocusPocus downloads packages only from this site and
checks their SHA-256 before importing them.

## Easiest way / La forma más fácil

Open **Issues → New issue → Submit a template**, attach the file (rename
`.hptemplate` to `.zip`) and send it. A bot validates it and opens the pull request
for you; the template is published when a maintainer merges it. HocusPocus has a
**Share with the community** button that downloads the file and opens this form
already filled in.

Abre **Issues → New issue → Enviar una plantilla**, adjunta el archivo (cambia
`.hptemplate` por `.zip`) y envíalo. Un bot lo valida y abre el pull request; se
publica cuando un responsable lo aprueba. En HocusPocus, el botón **Compartir en la
comunidad** descarga el archivo y abre este formulario ya rellenado.
