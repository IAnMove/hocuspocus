# Plan: plantillas de usuario y de la comunidad (crear, compartir, importar)

Fecha: 28 de septiembre de 2026. Responsable: Claude. Estado: **T1 en revisión (PR abajo); T2 en curso**.
Sin migraciones: empezamos de cero. Las plantillas antiguas guardadas en el
navegador (`localStorage`, `hocuspocus-world3d-user-templates`) no se leen ni se
borran; la biblioteca nueva vive en el servidor.

## 1. Objetivo

Cualquiera puede convertir una escena en **plantilla reutilizable** (con huecos
para sus recursos y controles ajustables), guardarla en su biblioteca, exportarla
como fichero, importarla de otra persona y compartirla en un **sitio de la
comunidad**. Personas y LLM (por MCP) usan la misma biblioteca y el mismo formato.
Primero Video 3D; Video 2D con el mismo formato.

## 2. Frontera con Grok (no pisarse)

| Grok (encargos M0–M9 y G1–G6) | Claude (este plan) |
|---|---|
| Catálogo de las plantillas **incluidas** en JSON compartido (M1), `scenes.catalog` (M2), esquema/validación (M3), compilar plantillas incluidas en el navegador sin interfaz (M4), vista previa (M5), edición por operaciones (M6), inventario de recursos (M7), guía y planificador (M8), prueba MCP (M9). Editor de vídeo: blur/focal, acortar canción, preajustes (G3–G6). | Plantillas **de usuario y de la comunidad**: formato `.hptemplate`, biblioteca en el servidor, `templates.*` (HTTP + MCP), guardar/aplicar/importar/exportar, interfaz en Video 3D y Video 2D, cliente del índice comunitario y sitio web comunitario. |

Punto de contacto: cuando exista `scenes.catalog` (M2), sus resultados incluirán las
plantillas de la biblioteca leyendo `services.template_library.TemplateLibrary.summaries()`
(`source: "user" | "community"`). Si M2 se fusiona antes que T1, Claude añade esa
integración en T1; si después, lo hace Grok en M2 llamando a esa función. Nadie más
toca los ficheros del otro lado.

## 3. Lo que ya existe

- `ui/src/features/scene3d/userTemplates.ts` + `Scene3DUserTemplates.tsx`: guardar un
  plano como plantilla (`hocuspocus.world3d.template` v1), exportar/importar JSON,
  en `localStorage` (máx. 24, 1,5 MB). Sin huecos declarados, sin controles, sin autoría.
- `app/services/scene_packages.py`: paquetes Video 3D portátiles (`.zip`), medios por
  SHA-256, límites, preflight, rechazo de extensiones de cine y enlaces externos.
  Se reutilizan sus utilidades de lectura segura de zip y de medios.

## 4. Formato `.hptemplate` (v1)

Zip con:

```
template.json      manifiesto (abajo)
document.json      escena Video 3D (world3d) o Video 2D (scene2d) v1
preview.jpg|png    miniatura (opcional, ≤ 2 MB)
media/<sha256>.<ext>  medios de ejemplo (opcionales)
```

```jsonc
{
  "kind": "hocuspocus.template", "version": 1,
  "id": "theinaog/rocket-launch",          // autor/slug, [a-z0-9-], único
  "editor": "video3d" | "video2d",
  "title": "Rocket launch", "description": "…", "tags": ["space", "launch"],
  "author": {"name": "Ina", "x": "theinaog", "url": "https://…"},
  "license": "CC-BY-4.0",                  // lista cerrada: CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, CC-BY-NC-4.0, MIT, all-rights-reserved
  "templateVersion": "1.0.0",
  "createdAt": "…", "updatedAt": "…",
  "requires": {"format": "world3d-1" | "scene2d-1", "app": ">=0.9.0"},
  "slots": [{"id": "hero", "label": "Protagonista", "hint": "Personaje de cuerpo entero",
             "accepts": ["model3d", "image"], "required": true,
             "target": "subject_1"}],        // video3d: id de slot; video2d: id de capa
  "controls": [{"id": "duration", "label": "Duración", "type": "number", "pointer": "/duration",
                "min": 2, "max": 60, "default": 8}],   // number | text | color | boolean | choice
  "preview": "preview.jpg",
  "media": [{"path": "media/<sha>.png", "sha256": "…", "bytes": 12345, "type": "image"}]
}
```

Reglas:
- Solo datos; nunca código. JSON ≤ 2 MB por miembro; zip ≤ 64 MB; ≤ 64 medios; tipos de
  medio permitidos (png, jpg, webp, glb, gltf, mp4, webm, wav, mp3, ogg, m4a).
- Sin rutas absolutas, `..`, enlaces simbólicos ni URL externas en el documento.
- Los medios del documento se referencian como `media/<sha>.<ext>` dentro del paquete;
  al aplicar en un workspace se copian allí y se reescriben a `/api/v1/file/...`.
- `controls[].pointer` es un JSON Pointer que debe existir en el documento.
- Se acepta importar un `*.world3d.template.json` antiguo: se convierte (huecos = slots con
  medio vacío; sin controles).

## 5. Biblioteca en el servidor

- Raíz: `HOCUS_TEMPLATE_LIBRARY_DIR`, o `$PINOKIO_HOME/cache/maestro/template-library`,
  como la biblioteca de estilos. Una carpeta por plantilla (`<autor>/<slug>/`) con los
  mismos miembros que el zip, más `origin.json` (`source: user | imported | community`,
  fecha, sha256 del paquete importado).
- Escritura atómica; `templateVersion` y `updatedAt`; guardar con el mismo id exige
  `expected_updated_at` (compare-and-swap) salvo `replace: true` explícito al importar.

## 6. Operaciones (HTTP `/api/v1/templates…` y MCP `templates.*`)

| MCP | HTTP | Qué hace |
|---|---|---|
| `templates.list` | `GET /api/v1/templates?editor=&tag=&q=` | Resúmenes (id, título, editor, autor, licencia, etiquetas, huecos, controles, miniatura URL, origen). |
| `templates.get` | `GET /api/v1/templates/{id}` | Manifiesto + documento. |
| `templates.save` | `POST /api/v1/templates` | Crea/actualiza desde un documento + metadatos + huecos/controles; medios opcionales desde el workspace. |
| `templates.apply` | `POST /api/v1/templates/{id}/apply` | `{workspace, slots:{id: fuente}, controls:{id: valor}}` → documento listo (copia medios de ejemplo usados al workspace). No guarda. |
| `templates.export` | `GET /api/v1/templates/{id}/package` | Descarga `.hptemplate`. Por MCP: publica el fichero en un workspace y devuelve su URL. |
| `templates.preflight` | `POST /api/v1/templates/preflight` | Lee un `.hptemplate` (subido o de un workspace) y dice qué trae, qué falta, avisos y si se puede importar. |
| `templates.import` | `POST /api/v1/templates/import` | Importa tras el preflight; `replace` para sobrescribir el mismo id. |
| `templates.delete` | `DELETE /api/v1/templates/{id}` | Borra de la biblioteca (pide confirmación en la UI). |

Todas versionadas (`{version: 1, input}`), con `intent_id` en las mutaciones y errores
con `code` estable.

## 7. Bloques

| Bloque | Contenido |
|---|---|
| **T1** | Formato, validación, biblioteca, operaciones HTTP + MCP, tests (incluye import de `.world3d.template.json` antiguo y aplicar con copia de medios). Doc `docs/templates/TEMPLATE_PACKAGES.md`. |
| **T2** | Video 3D: «Mis plantillas» sobre la biblioteca del servidor (guardar con huecos/controles/autoría/licencia, aplicar, exportar, importar con preflight, borrar). Se deja de usar `localStorage`. i18n es/en. |
| **T3** | Video 2D: «Guardar como plantilla» y biblioteca en el Scene Animator; `templates.apply` para `video2d`. |
| **T4** | Comunidad en la app: pestaña «Comunidad» que lee un `index.json` remoto (URL configurable, solo al abrirla), comprueba sha256 y tamaño, preflight e importación. |
| **T5** | Sitio comunitario: repo público `hocuspocus-community` con `templates/<autor>/<slug>.hptemplate`, CI que valida cada paquete con el mismo validador y genera `index.json` y una web estática (GitHub Pages) con fichas, filtros, vista previa, autor (@X) y descarga. Aportaciones por PR (moderación = revisión). **Crear el repo público y activar Pages requiere el visto bueno del usuario.** |

Después (fuera de este plan): packs de efectos, rótulos y fuentes con el mismo índice
(`kind` en el índice ya lo prevé), valoraciones y «abrir en HocusPocus» con un enlace.

## 8. Riesgos

- Deriva de formato: `requires.format` y `requires.app`; el preflight avisa si la app es
  más antigua o si el documento trae campos desconocidos.
- Privacidad y licencias: por defecto se exporta **sin medios**; incluirlos es explícito y
  pide licencia. Caras de personas reales: aviso en la UI.
- Seguridad: solo datos, límites de tamaño, lista de tipos, sin rutas ni enlaces externos.

## 9. Registro

| Bloque | PR | Estado |
|---|---|---|
| T1 | | en curso |
| T2 | | pendiente |
| T3 | | pendiente |
| T4 | | pendiente |
| T5 | | pendiente (necesita OK para crear el repo público) |
