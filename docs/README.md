# Documentación de HocusPocus

Tres tipos de documento, marcados en cada línea:

- **guía**: cómo usar o mantener algo hoy; se corrige cuando la app cambia.
- **contrato vivo**: comportamiento que el código y los tests cumplen; se cambia junto al código.
- **histórico**: evidencia de una decisión o auditoría pasada; no se actualiza y no es una lista de tareas.

El estado del proyecto está en [`CHANGELOG.md`](../CHANGELOG.md) y en el
[tablero de producción](development/PRODUCTION_WORK_BOARD.md). Los contratos de desarrollo
tienen su propio índice en [`development/README.md`](development/README.md).

## Empezar

- [APP_USER_GUIDE.md](APP_USER_GUIDE.md) — guía · qué es cada pestaña y a dónde ir después.
- [HOWUSEIT.md](HOWUSEIT.md) — guía · índice de las guías de operador por subsistema.
- [../README.md](../README.md) — guía · instalación, requisitos, API HTTP y créditos.
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — guía · cómo contribuir y validar un PR.

## Guías de operador (por subsistema)

- [3d-video-compositor/HOWUSEIT.md](3d-video-compositor/HOWUSEIT.md) — guía · compositor 3D programático (Scene Animator).
- [character-kits/HOWUSEIT.md](character-kits/HOWUSEIT.md) — guía · kits de personaje 2D y Face Rig.
- [character-kits/SPEECH_QUALITY.md](character-kits/SPEECH_QUALITY.md) — guía · calidad del habla 2D, packs de bocas y su API.
- [cut-paper/HOWUSEIT.md](cut-paper/HOWUSEIT.md) — guía · ejemplo Tijeral de animación recortable y descargas opcionales.
- [image-studio/HOWUSEIT.md](image-studio/HOWUSEIT.md) — guía · intenciones y edición en Studio → Imagen.
- [tools/HOWUSEIT.md](tools/HOWUSEIT.md) — guía · Studio Tools: upscale, revoice, quitar fondo.
- [video-editor/HOWUSEIT.md](video-editor/HOWUSEIT.md) — guía · Video Editor y mezclas ensambladas.
- [video-editor/MONTAGES.md](video-editor/MONTAGES.md) — guía · montajes editables y export Video 2D en servidor.
- [templates/TEMPLATE_PACKAGES.md](templates/TEMPLATE_PACKAGES.md) — guía · plantillas de escena compartibles (`.hptemplate`).
- [workspaces/HOWUSEIT.md](workspaces/HOWUSEIT.md) — guía · pestaña Workspaces (hilos de Director).
- [help/HELP_OVERLAY.md](help/HELP_OVERLAY.md) — guía · mantenimiento del tutorial de ayuda dentro de la app.
- [MAESTRO_X_STORY_COMICS_VIDEO.md](MAESTRO_X_STORY_COMICS_VIDEO.md) — guía · Story → Comics → Video con un solo canon.
- [DLSS5.md](DLSS5.md) — guía · puente DLSS opcional en postprocesado y Tools.

## Series Lab y agentes

- [series-lab/CHATGPT_MCP.md](series-lab/CHATGPT_MCP.md) — guía · hacer una serie con ChatGPT conectado por MCP y OAuth.
- [series-lab/IMPLEMENTATION.md](series-lab/IMPLEMENTATION.md) — contrato vivo · modelo, persistencia, superficie HTTP y MCP de Series Lab.
- [series-lab/PHASE0_ARCHITECTURE.md](series-lab/PHASE0_ARCHITECTURE.md) — histórico · arquitectura aprobada de la fase 0.
- [series-lab/series-library-v1.schema.json](series-lab/series-library-v1.schema.json), [series-lab/example-series-library-v1.json](series-lab/example-series-library-v1.json), [series-lab/series-assembly.openapi.json](series-lab/series-assembly.openapi.json) — contrato vivo · esquema de la biblioteca, ejemplo y OpenAPI del montaje.
- [agents/VIDEO_PRODUCTION_RUNBOOK.md](agents/VIDEO_PRODUCTION_RUNBOOK.md) — guía · videoclip completo desde una spec por MCP.
- [agents/VIDEO2D_MCP_GUIDE.md](agents/VIDEO2D_MCP_GUIDE.md) — guía · montar una escena Video 2D por MCP.
- [agents/MODEL3D_MCP.md](agents/MODEL3D_MCP.md) — guía · Model3D por MCP.
- [agents/MODEL3D_COMPOSE.md](agents/MODEL3D_COMPOSE.md) — guía · componer un modelo low-poly en CPU.
- [agents/HUMANOID_RIG.md](agents/HUMANOID_RIG.md) — guía · rig humanoide para mallas reales.

## Contratos de producto

- [COMIC_VIDEO_ADAPTATION.md](COMIC_VIDEO_ADAPTATION.md) — contrato vivo · cómo un cómic terminado se adapta a vídeo.
- [minimax-h3-prompting.md](minimax-h3-prompting.md) — contrato vivo · fuentes canónicas del prompting de MiniMax H3.
- [h3-prompt-revisions.md](h3-prompt-revisions.md) — contrato vivo · registro de cambios del compilador de prompts H3.
- [WIZARD_ACCEPTANCE_TESTING.md](WIZARD_ACCEPTANCE_TESTING.md) — guía · pruebas de aceptación del Wizard con navegador.

## Ejemplos

Cada carpeta de [`examples/`](examples/) documenta un paquete de ejemplo (plantillas, clips y procedencia). Los medios se descargan bajo demanda (ver [OPTIONAL_EXAMPLES](development/OPTIONAL_EXAMPLES.md)):
ashes-oath, creative, cut-paper, dark-fantasy, dark-stillness, dark-worlds, face-pack, kingdom-road, living-worlds, mar-sin-nombre, moving-cutouts, oath-heroes, perspective-lab, portal-rides, skate-portal, skate-portal-v2, topdown-cliff-flight, topdown-dragon-portals.

## Histórico

- [AUDITORIA_CODIGO_UI_2026-08-13.md](AUDITORIA_CODIGO_UI_2026-08-13.md) — histórico · auditoría de código y UI de agosto de 2026.
- [AUDIT_REMEDIATION_STATUS_2026-08-16.md](AUDIT_REMEDIATION_STATUS_2026-08-16.md) — histórico · estado de remediación de esa auditoría.
- [eval-selection-baseline.md](eval-selection-baseline.md) — histórico · baseline T0.5 de selección de plantillas.
- [scene-recipe-gap.md](scene-recipe-gap.md) — histórico · auditoría T2.3 de qué no sobrevive de Scene a Recipe.
- [archive/](archive/README.md) — histórico · handoffs, ola de arquitectura F1–F12 y la auditoría de cobertura del Wizard de septiembre.

`images/` guarda las capturas que usan el README y las guías.
