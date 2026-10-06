# Documentación de desarrollo

Una línea por fichero. Tipos: **guía** (cómo hacer algo hoy), **contrato** (lo que el código y los
tests cumplen; cambia con el código), **plan** (trabajo en curso o pausado, con su estado), **brief**
(encargo escrito para otro agente; el tablero manda si difieren), **histórico** (evidencia de una
decisión; no se actualiza). El estado general está en [`CHANGELOG.md`](../../CHANGELOG.md).

## Empieza aquí

- [CURRENT_WORK.md](CURRENT_WORK.md) — puntero · el estado vive en el CHANGELOG y en el tablero.
- [PRODUCTION_WORK_BOARD.md](PRODUCTION_WORK_BOARD.md) — plan · tablero de la producción de videoclips: bloques, dueños, ramas y estado.
- [BRANCHING.md](BRANCHING.md) — contrato · `development` integra, `main` publica; worktrees y PRs.
- [AGENT_QA_POLICY.md](AGENT_QA_POLICY.md) — contrato · política mínima de QA para agentes, `CI required` y validador de evidencia.
- [LOCAL_VALIDATION.md](LOCAL_VALIDATION.md) — guía · validación local sin proveedores (`scripts/validate_local.sh`).
- [CODE_HEALTH.md](CODE_HEALTH.md) — contrato · ratchet de salud de código para Python y `ui/src`.
- [CI_CACHE_AND_SHARDS.md](CI_CACHE_AND_SHARDS.md) — contrato · cachés de CI y shards de pytest.
- [TASK_COST_REPORT.md](TASK_COST_REPORT.md) — contrato · informe de coste obligatorio en cada PR.
- [MERGE_ELIGIBILITY.md](MERGE_ELIGIBILITY.md) — contrato · simulación de elegibilidad de merge (nunca mezcla).
- [QA_ACCEPTANCE.md](QA_ACCEPTANCE.md) — contrato · revisión independiente y validador de aceptación.
- [GITHUB_PROTECTION.md](GITHUB_PROTECTION.md) — histórico · protección de ramas inspeccionada el 2026-09-05.
- [EXECUTION_BASELINE.md](EXECUTION_BASELINE.md) — contrato · autoridades de ejecución vigentes; enlaza al baseline archivado.

## Arquitectura, dominio e instalación

- [ARCHITECTURE_FOUNDATION.md](ARCHITECTURE_FOUNDATION.md) — contrato · contratos ejecutables de la base canónica.
- [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md) — contrato · mapa de arquitectura generado en build para el área de desarrollador.
- [DOMAIN_MODEL_AND_ASSET_PROVENANCE.md](DOMAIN_MODEL_AND_ASSET_PROVENANCE.md) — contrato · modelo de dominio y provenance de assets.
- [GENERATION_RECORD.md](GENERATION_RECORD.md) — contrato · generation record v1 ([esquema](generation-record-v1.schema.json)).
- [ASSET_LIBRARY.md](ASSET_LIBRARY.md) — contrato · biblioteca de recursos CC0 y descargador seguro ([esquema](asset-library-v1.schema.json)).
- [asset-manifest-v1.schema.json](asset-manifest-v1.schema.json), [production-record-v1.schema.json](production-record-v1.schema.json), [project-record-v1.schema.json](project-record-v1.schema.json), [run-record-v1.schema.json](run-record-v1.schema.json), [workspace-record-v1.schema.json](workspace-record-v1.schema.json), [qa-evidence.schema.json](qa-evidence.schema.json), [merge-eligibility.schema.json](merge-eligibility.schema.json) — contrato · esquemas JSON de los registros.
- [ASSET_PICKER_MIGRATION.md](ASSET_PICKER_MIGRATION.md) — histórico · inventario y contrato del selector universal de recursos (septiembre de 2026).
- [INTERNATIONALIZATION.md](INTERNATIONALIZATION.md) — contrato · i18n: `en` es la fuente, `es` el segundo catálogo.
- [RUNTIME_PROFILES.md](RUNTIME_PROFILES.md) — contrato · recetas por plataforma, runtimes aislados y recuperación.
- [MACOS_COMPATIBILITY.md](MACOS_COMPATIBILITY.md) — contrato · core/remoto en Apple Silicon.
- [REACT_INSTALLATION.md](REACT_INSTALLATION.md) — guía · instalación, reparación e identidad de build de la UI.
- [STORAGE_CLEANUP.md](STORAGE_CLEANUP.md) — contrato · liberación de ficheros intermedios al terminar y al arrancar.
- [OPTIONAL_EXAMPLES.md](OPTIONAL_EXAMPLES.md) — contrato · colecciones de medios de ejemplo opcionales.
- [WANGP_1272_ADOPTION.md](WANGP_1272_ADOPTION.md) — contrato · adopción de WanGP 12.72.
- [WANGP_1300_AUDIO.md](WANGP_1300_AUDIO.md) — contrato · YuE2, AuK y la web móvil de Deepy (WanGP 13.00).
- [STUDIO_PANEL_LAYOUT_REVIEW.md](STUDIO_PANEL_LAYOUT_REVIEW.md) — histórico · revisión de la distribución de paneles de Studio (septiembre de 2026).

## Comandos compartidos: Wizard, MCP y UI

- [SHARED_NATIVE_COMMANDS.md](SHARED_NATIVE_COMMANDS.md) — guía · usar los comandos compartidos desde el Wizard o un cliente MCP.
- [WIZARD_MCP_USAGE.md](WIZARD_MCP_USAGE.md) — guía · guía de uso del corpus de comandos publicados.
- [MCP_RECOVERABILITY.md](MCP_RECOVERABILITY.md) — contrato · qué deja cada herramienta MCP y acción del Wizard, dónde lo encuentra y edita el usuario (vista «Agentes» de Actividad) y qué falta.
- [IMAGE_COMMANDS.md](IMAGE_COMMANDS.md), [MUSIC_COMMANDS.md](MUSIC_COMMANDS.md), [SFX_COMMANDS.md](SFX_COMMANDS.md), [SPEECH_COMMANDS.md](SPEECH_COMMANDS.md), [TOOLS_COMMANDS.md](TOOLS_COMMANDS.md), [WORKSPACE_COMMANDS.md](WORKSPACE_COMMANDS.md) — contrato · admisión de comandos por dominio.
- [SCENE_EFFECTS_AND_MCP.md](SCENE_EFFECTS_AND_MCP.md) — contrato · SFX de escena, voz y cómo activar y conectar MCP.
- [WIZARD_ACTION_RUNNER.md](WIZARD_ACTION_RUNNER.md) — contrato · runner de acciones del Wizard y adaptadores de aplicación.
- [WIZARD_WORKFLOW_RUNTIME.md](WIZARD_WORKFLOW_RUNTIME.md) — contrato · runtime de workflows duraderos del Wizard.
- [WIZARD_RHYTHMIC_VIDEO3D.md](WIZARD_RHYTHMIC_VIDEO3D.md) — contrato · workflow rítmico de Vídeo 3D desde el Wizard.
- [WIZARD_PROGRAMMATIC_VIDEO.md](WIZARD_PROGRAMMATIC_VIDEO.md) — contrato · Wizard → composición de vídeo (Scene recipe).
- [WIZARD_NIGHTLY.md](WIZARD_NIGHTLY.md) — guía · validación nocturna del Wizard (`scripts/nightly_wizard_*`).
- [LABS_WIZARD_ACTION_MATRIX.md](LABS_WIZARD_ACTION_MATRIX.md) — contrato · matriz Labs ↔ Wizard (fixture L0 con test).

## Música e historias

- [MUSIC_SUBMISSION.md](MUSIC_SUBMISSION.md) — contrato · envío de música: biblioteca Story + TaskRegistry.
- [MUSIC_FINALIZATION.md](MUSIC_FINALIZATION.md) — contrato · publicación en servidor de un intento musical reservado.
- [MUSIC_MODEL_CONTRACT.md](MUSIC_MODEL_CONTRACT.md) — contrato · un catálogo decide disponibilidad y compilación.
- [LYRICS_LANGUAGE.md](LYRICS_LANGUAGE.md) — contrato · idioma de la letra y guardia de encolado.
- [STORY_SONG_IDENTITY.md](STORY_SONG_IDENTITY.md) — contrato · identidad de la canción de una historia.
- [SOURCE_AUDIO_LYRIC_TIMELINE.md](SOURCE_AUDIO_LYRIC_TIMELINE.md) — contrato · timeline de letra alineada con el audio fuente.
- [MUSIC_MOTION_PACK.md](MUSIC_MOTION_PACK.md) — contrato · paquete de movimientos musicales v3 (`musicMotionCatalog.ts`).

## Producción: videoclips, tráilers y episodios

- [UNIFIED_PRODUCTIONS.md](UNIFIED_PRODUCTIONS.md) — contrato · una obra de vídeo con proyecto, producción y ejecuciones.
- [PRODUCTION_PACKAGE_EVALUATION.md](PRODUCTION_PACKAGE_EVALUATION.md) — contrato · evaluación offline de paquetes de producción.
- [PRODUCTION_QUALITY_ANALYSIS_2026-09-29.md](PRODUCTION_QUALITY_ANALYSIS_2026-09-29.md) — histórico · por qué bajó la calidad de los videoclips y qué se cambió.
- [GROK_PRODUCTION_NEXT_2026-09-29.md](GROK_PRODUCTION_NEXT_2026-09-29.md) — brief · numeración de los puntos de producción que usa el tablero.
- [GROK_PRODUCTION_BLOCKS_2026-09-30.md](GROK_PRODUCTION_BLOCKS_2026-09-30.md) — brief · detalle de los bloques 0, D, C y B repartidos a Grok.
- [GROK_COMIC_TO_VIDEO_2026-10-01.md](GROK_COMIC_TO_VIDEO_2026-10-01.md) — brief · cómic → película y cómic → tráiler sin pasos manuales.
- [MONTAGE_SHOT_BOARD_PLAN.md](MONTAGE_SHOT_BOARD_PLAN.md) — plan · «plano a plano» en el Video Editor (S1–S3 hechos; S4 pendiente).
- [GROK_VIDEO2D_BOOST_PLAN_2026-09-27.md](GROK_VIDEO2D_BOOST_PLAN_2026-09-27.md) — plan · mejora del creador Video 2D (B0–B3 en sus PRs).

## MiniMax H3

- [H3_IMPLEMENTATION_NOTES.md](H3_IMPLEMENTATION_NOTES.md) — contrato · registro de implementación de la adopción H3.
- [H3_BENCHMARK_2026-09-06.md](H3_BENCHMARK_2026-09-06.md) — histórico · benchmark Seinfeld; fuente de `ui/src/lib/h3Catalog.ts`.
- [H3_EXTENDED_DURATION.md](H3_EXTENDED_DURATION.md) — contrato · pase experimental de 30 segundos (flag opt-in).
- [H3_SEMANTIC_BRIDGE_PLAN.md](H3_SEMANTIC_BRIDGE_PLAN.md) — plan · puente semántico opcional; adaptador implementado, flag apagado.
- [minimax-h3-fast-runtime-research.md](minimax-h3-fast-runtime-research.md) — histórico · investigación de runtime rápido (agosto de 2026).

## Vídeo 2D, 2,5D y procedural

- [PROCEDURAL_VIDEO_ROADMAP.md](PROCEDURAL_VIDEO_ROADMAP.md) — plan · vídeo procedural por fases y PRs (P00–P12).
- [procedural-video/ANIME_LIMITED_ANIMATION.md](procedural-video/ANIME_LIMITED_ANIMATION.md), [CAMERAS.md](procedural-video/CAMERAS.md), [FILTERS.md](procedural-video/FILTERS.md), [SCENES_2D_25D.md](procedural-video/SCENES_2D_25D.md), [SCENES_3D.md](procedural-video/SCENES_3D.md) — plan · backlog por bloque de la hoja de ruta procedural.
- [PROCEDURAL_3D_SCENE_SPEC.md](PROCEDURAL_3D_SCENE_SPEC.md) — contrato · spec de escena procedural 3D (G3) y pestaña Vídeo 2,5D.
- [PROCEDURAL_MUSIC_VIDEO_V3.md](PROCEDURAL_MUSIC_VIDEO_V3.md) — plan · videoclips procedurales v3.
- [SCENE_TEMPLATE_LIBRARY.md](SCENE_TEMPLATE_LIBRARY.md) — guía · plantillas procedurales con assets de Library.
- [SCENE_TEMPLATE_REVIEW.md](SCENE_TEMPLATE_REVIEW.md) — guía · sandbox de revisión del catálogo de plantillas.
- [SCENE_SHOWCASE.md](SCENE_SHOWCASE.md) — guía · showcase portable de escenas.
- [TEMPLATE_LIBRARY_PLAN_2026-09-28.md](TEMPLATE_LIBRARY_PLAN_2026-09-28.md) — plan · plantillas de usuario y comunidad (T1–T4 en #532; pausado).
- [CHARACTER_SPEECH_RASTER_PLAN.md](CHARACTER_SPEECH_RASTER_PLAN.md) — plan · personajes raster que hablan.
- [CHARACTER_SPEECH_WORKSHOP.md](CHARACTER_SPEECH_WORKSHOP.md) — plan · taller de habla 2D con preparación manual.
- [GLB_ANIMATION_IMPORT_CONTRACT.md](GLB_ANIMATION_IMPORT_CONTRACT.md) — contrato · importación de animaciones GLB.

## Vídeo 3D

- [VIDEO3D_PRODUCTION_PLAN.md](VIDEO3D_PRODUCTION_PLAN.md) — plan · producción programática y animación dialogada.
- [VIDEO3D_BASELINE.md](VIDEO3D_BASELINE.md) — histórico · caracterización del editor antes de cambiar contratos.
- [VIDEO3D_EDITOR_REFRESH.md](VIDEO3D_EDITOR_REFRESH.md) — contrato · plantillas y controles de edición.
- [VIDEO3D_GENERATION_POLICY.md](VIDEO3D_GENERATION_POLICY.md) — contrato · política de generación de assets de recetas.
- [VIDEO3D_SHOT_REVIEW.md](VIDEO3D_SHOT_REVIEW.md) — contrato · planos animados y números de revisión.
- [VIDEO3D_TEMPLATE_REVIEW_PLAN.md](VIDEO3D_TEMPLATE_REVIEW_PLAN.md) — plan · Wizard, escenas reutilizables y revisión visual.
- [VIDEO3D_SPEECH.md](VIDEO3D_SPEECH.md) — contrato · voz y labios en Vídeo 3D.
- [VIDEO3D_SPEECH_PRODUCTIONS.md](VIDEO3D_SPEECH_PRODUCTIONS.md) — contrato · lip-sync 3D desde canciones, capítulos y tráileres.
- [VIDEO3D_EXPORT_QUALITY.md](VIDEO3D_EXPORT_QUALITY.md) — contrato · niveles de exportación borrador/final/máster.
- [VIDEO3D_LOOK.md](VIDEO3D_LOOK.md) — contrato · iluminación por entorno y look.
- [VIDEO3D_GEOMETRY_CHECKS.md](VIDEO3D_GEOMETRY_CHECKS.md) — contrato · comprobaciones de geometría antes del render.
- [ATMOS_SETS.md](ATMOS_SETS.md) — contrato · escenarios procedurales de luz y atmósfera, con la receta para añadir un set.
- [GROK_ATMOSPHERE_SETS_2026-09-29.md](GROK_ATMOSPHERE_SETS_2026-09-29.md) — brief · encargo original de los escenarios atmosféricos.
- [PS1_BACKPLATE_TEMPLATE.md](PS1_BACKPLATE_TEMPLATE.md) — contrato · escena estilo PS1 con gráficos prerenderizados.
- [QWEN_PS1_BACKPLATES.md](QWEN_PS1_BACKPLATES.md) — contrato · Qwen por defecto y fondos prerenderizados.
- [WORLD3D_TEMPLATES_AGENTS.md](WORLD3D_TEMPLATES_AGENTS.md) — guía · plantillas de Vídeo 3D para agentes (una sola biblioteca).
- [MODEL3D_ENGINES.md](MODEL3D_ENGINES.md) — contrato · adaptadores TRELLIS.2 y Pixal3D.
- [HUMANOID_HANDS_RESEARCH.md](HUMANOID_HANDS_RESEARCH.md) — histórico · investigación de manos antes de añadir huesos de dedos (4.F5).
- [calidad-local/01-render-master.md](calidad-local/01-render-master.md), [02-iluminacion-hdri-lut.md](calidad-local/02-iluminacion-hdri-lut.md), [03-biblioteca-cc0.md](calidad-local/03-biblioteca-cc0.md), [04-personajes-3d.md](calidad-local/04-personajes-3d.md), [05-sonido.md](calidad-local/05-sonido.md), [06-control-calidad.md](calidad-local/06-control-calidad.md) — plan · hoja de ruta de calidad local en seis fases (PRs #770–#801).

## Series

- [SERIES_ANIMADAS_PLAN_2026-10-04.md](SERIES_ANIMADAS_PLAN_2026-10-04.md) — plan · series de animación fáciles en tres fases (1A–3 en #802–#805).
- [SERIE_ANIMADA_MCP_PROBLEMAS_2026-10-04.md](SERIE_ANIMADA_MCP_PROBLEMAS_2026-10-04.md) — histórico · problemas del 1x02 hecho por MCP y sus arreglos.
