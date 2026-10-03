# Grok: continuar las plantillas compartibles (.hptemplate) y la comunidad

Fecha: 28 de septiembre de 2026. Autor: Claude (revisará cada paso). Ejecutor: Grok.

## 1. Punto de partida

Todo el trabajo previo está en el **PR #532 en borrador**
(<https://github.com/IAnMove/hocuspocus/pull/532>, rama `feat/template-library`).
Antes de nada lee en esa rama:

- `docs/development/TEMPLATE_LIBRARY_PLAN_2026-09-28.md` (plan completo y **§10: resumen,
  decisiones y pasos para retomar**).
- `docs/templates/TEMPLATE_PACKAGES.md` (formato, API, comunidad).
- `community/README.md` y `community/repo-seed/` (semilla del repo comunitario).

Qué hay hecho: formato `.hptemplate` v1 (huecos, controles por JSON Pointer, autor con @X,
licencia, etiquetas, miniatura, medios por SHA-256), biblioteca en el servidor, HTTP
`/api/v1/templates…`, MCP `templates.*` y `templates.community.*`, «Mis plantillas» en
Video 3D y Video 2D (panel común `ui/src/features/templates/TemplateLibraryPanel.tsx`),
pestaña Comunidad (descarga en el servidor con lista de dominios y SHA-256), botón
Compartir (formulario de issue rellenado), `scripts/community_index.py` y la semilla del
repo comunitario (web estática, GitHub Pages, formulario de envío y bot que abre el PR).

Decisiones que se mantienen:

- Sin migraciones de lo guardado antes en el navegador.
- Comunidad sobre GitHub (sin servidor propio): nada se publica sin que el propietario
  fusione; el CI valida cada paquete con el importador de la app.
- **YouTube solo para ver** (vistas previas, galería, tutoriales); nunca como fuente de
  medios de escenas (sus condiciones prohíben descargar).
- Ahora Grok lleva también las plantillas incluidas (M0–M9): puede integrar ambas cosas.

## 2. Reglas (como en los encargos anteriores)

1. Trabaja en tu worktree (`/home/ina/hocuspocus-worktrees/<rama>`); **nunca** edites
   `/mnt/extras/pinokio/api/hocuspocus-development` (servidor en vivo).
2. **Continúa en la misma rama y PR #532** (no apiles PRs encima). Actualízala con
   `origin/development` (rebase o merge, sin perder commits) y mantenla en borrador hasta
   terminar C0–C4; entonces márcala lista y pide revisión a Claude. No la fusiones tú.
3. Sin GPU ni proveedores. Sin crear repos, activar Pages ni publicar nada en internet
   (eso es C5 y necesita el OK explícito del usuario).
4. Validación en cada commit que subas: pytest de lo tocado
   (`tests/test_template_library.py` como mínimo), `cd ui && npm run check`,
   `BASE_REF=origin/development bash scripts/check_code_health_pr_base.sh`,
   `python3 scripts/check_documentation_links.py`, `python scripts/verify_clean_repo.py`,
   fixture de rutas (`python scripts/architecture_contracts.py --write`) y
   `scripts/ci_test_groups.json`.
5. Funciones nuevas con complejidad ≤ 14 (el ratchet cuenta las ≥ 15). i18n es/en.
   Operaciones MCP versionadas `{version: 1, input}`, errores con `code` estable.
6. Mantén al día §9 y §10 del plan del PR con lo que hagas.

## 3. Tareas

### C0 — Retomar la rama
- [ ] Actualizar `feat/template-library` con `origin/development`, resolver conflictos
  (suelen ser `tests/fixtures/route_table.json`, `scripts/ci_test_groups.json` y
  `app/_launch_runtime.py`), regenerar la fixture de rutas y pasar toda la validación.

### C1 — Pendientes conocidos
- [ ] Sustituir `window.confirm` al borrar por una confirmación dentro de la tarjeta
  («¿Eliminar? Sí / No»): mejor en móvil y permite probarlo. Añadir el paso de borrar al
  test `ui/tests/scene3dTemplateLibraryUi.test.tsx` (hoy se omite porque `confirm` se
  cuelga en jsdom).
- [ ] Integrar la biblioteca en `scenes.catalog` (M2): incluir
  `TemplateLibrary.summaries()` con `source: user | imported | community` y que
  `templates.apply` sea la forma documentada de usarlas. Test de cobertura MCP (M0)
  actualizado.
- [ ] Añadir en la guía para agentes (M8) cómo usar `templates.*` y
  `templates.community.*`.

### C2 — Vídeo de YouTube como vista previa (T6a)
- [ ] Manifiesto: campo opcional `previewVideo: {provider: "youtube", id}`. Aceptar
  `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/` y `youtube-nocookie.com/embed/`,
  normalizar al id de 11 caracteres `[A-Za-z0-9_-]{11}` y rechazar el resto
  (`code: invalid_video`). Nunca descargar nada de YouTube.
- [ ] `templates.save` y el formulario de guardar aceptan la URL. La tarjeta muestra
  «Ver vídeo», que abre `https://www.youtube.com/watch?v=<id>` en una pestaña nueva; la app
  no incrusta YouTube salvo que el usuario pulse.
- [ ] `community_index.py` copia `previewVideo` al índice; `CommunityIndex` lo valida y la
  pestaña Comunidad muestra el enlace.
- [ ] Web comunitaria (`community/repo-seed/site/index.html`): miniatura
  `https://i.ytimg.com/vi/<id>/hqdefault.jpg` con botón de reproducir que solo al pulsar
  crea el `iframe` de `https://www.youtube-nocookie.com/embed/<id>`.

### C3 — Galería de vídeos hechos con HocusPocus (T6b)
- [ ] Nuevo formulario `community/repo-seed/.github/ISSUE_TEMPLATE/share-video.yml`
  (URL de YouTube, título, plantillas usadas por id `autor/slug`, @X, descripción, casilla
  de derechos) con etiqueta `video-submission`.
- [ ] Bot `.github/scripts/video_submission.py` + workflow: valida la URL, consulta el
  oEmbed público `https://www.youtube.com/oembed?url=<url>&format=json` (sin clave) para
  confirmar que existe y leer título/canal, comprueba que las plantillas citadas existen
  en `templates/`, añade la entrada a `showcase/videos.json` y abre el PR. Comentario de
  error en el issue si algo falla.
- [ ] `community_index.py`: incluir `videos` en `index.json` y enlazar plantilla ↔ vídeos
  (`usedIn` en cada plantilla).
- [ ] Web: sección «Hecho con HocusPocus» (tarjetas con la miniatura de YouTube que
  reproducen al pulsar y enlazan a sus plantillas); en cada plantilla, sus vídeos.
- [ ] Workflow semanal (`schedule`) que revisa con oEmbed que los vídeos siguen públicos
  y abre o actualiza un issue «Vídeos no disponibles» con la lista.
- [ ] En la app, pestaña Comunidad: «Vídeos que la usan» enlazando a YouTube.

### C4 — Pruebas y documentación
- [ ] Tests Python: normalización de URLs (válidas, inválidas, playlists, canales),
  índice con vídeos y `usedIn`, bot de vídeos con oEmbed simulado.
- [ ] Tests UI: enlace «Ver vídeo», borrar con la nueva confirmación, vídeos en Comunidad.
- [ ] Probar la web generada en local (escritorio y móvil, modo claro y oscuro) con una
  plantilla y un vídeo de ejemplo, y adjuntar capturas en el PR.
- [ ] Actualizar `docs/templates/TEMPLATE_PACKAGES.md`, `community/README.md`, el README de la
  semilla y §9–§10 del plan.

### C5 — Publicar (solo con OK explícito del usuario)
No lo ejecutes. Deja en el PR los comandos exactos para cuando el usuario diga «adelante»:
crear `IAnMove/hocuspocus-community` (público) con el contenido de `community/repo-seed/`,
activar GitHub Pages (fuente: GitHub Actions), crear las etiquetas `template-submission`
y `video-submission`, y comprobar que `DEFAULT_INDEX`
(`https://ianmove.github.io/hocuspocus-community/index.json`) y `COMMUNITY_REPO`
coinciden con la URL real.

## 4. Entrega

Cuando termines C0–C4: PR #532 listo para revisión con un resumen de qué se añadió,
ejemplos JSON (manifiesto con `previewVideo`, entrada de `videos.json`, fragmento de
`index.json`), salida de la validación, capturas de la web y qué queda fuera.
