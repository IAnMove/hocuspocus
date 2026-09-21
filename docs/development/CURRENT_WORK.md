# Estado de desarrollo y punto de entrada

Verificado el 21 de septiembre de 2026 contra `origin/development` **`e44ee001`**.
Es una fotografía con evidencia, no un sustituto de Git. Antes de reservar trabajo:
`git fetch origin development`, consultar PR abiertos y comprobar sus archivos.

## Instantánea documental — 21 septiembre 2026

Automatización semanal de docs sobre development (main sigue ~443 commits
atrás). Contratos nuevos o actualizados: Image Studio intents / local-edit /
Auto / Qwen 2.1 uncensored
([image-studio/HOWUSEIT](../image-studio/HOWUSEIT.md),
[IMAGE_COMMANDS](IMAGE_COMMANDS.md)); H3 30 s opt-in
([H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md)); voces grabadas
([character-kits/HOWUSEIT](../character-kits/HOWUSEIT.md)); AuK en
[SPEECH_COMMANDS](SPEECH_COMMANDS.md); proyección Story Music en
[GENERATION_RECORD](GENERATION_RECORD.md); Help y Tijeral
([help/HOWUSEIT](../help/HOWUSEIT.md), [cut-paper/HOWUSEIT](../cut-paper/HOWUSEIT.md)).
No implica publicación en main ni QA audiovisual.

## Correcciones de integración — 12 septiembre 2026

Rama `fix/integration-audit-20260912`, base `5f68eb12`, preparada para PR hacia
development. Ocho correcciones en generación, borradores, ejecución Wizard,
exportación World3D, inspector y revisión de producción. Evidencia y límites en
[INTEGRATION_AUDIT_2026-09-12](INTEGRATION_AUDIT_2026-09-12.md). No implica merge
ni publicación de la aplicación local.

## SFX, habla y MCP — 10 septiembre 2026

PR **#299** (draft hacia development), base integrada `729f784c`. Contrato:
[SCENE_EFFECTS_AND_MCP](SCENE_EFFECTS_AND_MCP.md). 30 efectos compartidos y
plantillas 2D/3D, galería de escenas nativas, voces con Rhubarb y separación
local opcional mediante BS-RoFormer instalado. Configuración MCP y operaciones compartidas.
Tres MP4 reales validados; la preparación MCP no equivale a render en servidor.
Ampliación de labios: controles por sujeto, colocación mediante clic, micrófono
y ejemplo inglés. Corregida conversión de coordenadas de piel animada. Contrato
[VIDEO3D_SPEECH](VIDEO3D_SPEECH.md).
Consultar el HEAD y sus checks en el PR antes de integrar. No es una publicación.

## Timeline de letra desde el audio — 11 septiembre 2026

La rama de trabajo de fidelidad musical conserva la letra escrita, la alinea con
palabras detectadas en el audio, genera SRT dentro de la aplicación y entrega al
Director offsets exactos para apariciones y acciones. Contrato y límites:
[SOURCE_AUDIO_LYRIC_TIMELINE](SOURCE_AUDIO_LYRIC_TIMELINE.md). Consultar PR y HEAD
vigentes antes de integrar; la evidencia local no equivale a publicación.

## Lectura mínima

YuE2 y AuK (WanGP 13.00): contrato de adopción y resultados de la investigación
de Deepy móvil en [WANGP_1300_AUDIO](WANGP_1300_AUDIO.md). Consultar el PR y su
HEAD antes de integrar; una rama de implementación no equivale a publicación.

Lee este documento y el contrato del dominio que vas a modificar. Para contribuir,
consulta [BRANCHING](BRANCHING.md) y [AGENT_QA_POLICY](AGENT_QA_POLICY.md).
La [cola](SLICE_QUEUE.md) contiene solo pendientes. No leas todo `docs/` ni el
[archivo histórico](../archive/README.md) al iniciar una sesión. Los planes antiguos
no autorizan acciones ni representan el estado actual.

## Integrado: no volver a implementar

| Trabajo | Evidencia de integración | Límite de la afirmación |
|---|---|---|
| Contrato de idioma de letras | #139, #141 | No garantiza fidelidad de toda canción generada |
| GenerationRecord con CAS y autoridad de proyección | #138, #142 | No es un segundo scheduler ni prueba cobertura de todos los productores |
| Reserva musical idempotente | #143 | Distinguir reserva, ejecución y publicación |
| Finalización musical en servidor | #158 | Revisar su contrato antes de proponer otra implementación |
| Catálogo/spec musical y rehidratación | #159, #160, #162; fake worker #163 | Fake worker no acredita calidad de audio real |
| Extracción I/O de estado Director | #167 | Locks, reconciliación, borrado y ejecución siguen en el pipeline |
| Adopción H3, guías y finalización de prompts | #170, #172, #174, #178, #179 | Mantener diálogos literales y fixtures; no rehacer refactor |
| Policy/idioma/Creative H3 | #185 | Pruebas de contrato no demuestran éxito audiovisual universal |
| Labs/Wizard L0–L12 | #182, #183, #186–#189, #192, #194, #196, #197 | Entregas integradas; #197 congela L1–L4 y L9 como resueltos. Quedan límites de validación indicados abajo |
| Vídeo procedural y galería/plantillas | #168, #169, #173, #175, #177, #180, #181, #184 | No equivale a completar toda la hoja de ruta procedural |
| Inspección GLB y parches faciales | #190, #193, #195 | Router de inspección de #195 todavía sin montar; parches tienen límites de piloto |
| Taller de habla 2D (preparación manual) | #200 | Panel, borrador, recarga y e2e simulado. El test del panel evita aserciones HTMLElement-vs-null (~260 MiB RSS). No es validación artística de un personaje hablando ni cierra R2–R4 |
| Series attemptId vs número de plano | #201 | `attempt_id` en un único shot selecciona esa toma histórica. `shot_numbers: [2]` sin `attempt_id` sigue siendo el último eligible del plano 2. No cubre móvil real ni GPU |
| Escenas 3D reales (editor + AssetExplorer inicial) | #198, merge `fae7d3f6` | Explorador inicial; el contrato transaccional está en #208 |
| Plantillas musicales vídeo 3D | #204 | Cámara `side` y plantillas de videoclip; `Scene3DWorkspace` ya no está reservado por un PR abierto |
| Copy i18n de Vídeo 3D / compositor | #205 | No cubre todo el chrome restante del laboratorio de plantillas |
| Inventario selector universal | #206 | Contrato e inventario; no implementa el picker |
| Contrato selector (PR 1) | #207, merge `f1855ab7` | Identidad, sort/paginación y adapters. No es el modal transaccional |
| Modal selector transaccional (PR 2) | #208, merge `059282ed` | Choose/Cancel/None; sin doble clic ni preselección. No es preview real ni dual origin |
| Set café vídeo 3D | #209 | Decorado texturizado; no es el picker |
| Preview selector (PR 3) | #210, merge `631c0d47` | Un reproductor/visor a demanda. No es el campo de doble origen |
| Campo doble origen (PR 4) | #211, merge `1e6cb636` | `AssetInput`. No migra todos los consumidores |
| Migración 2.5D/recetas (PR 5) | #213, merge `445250f7` | Narrative + recetas. Scene3DWorkspace no |
| Hunyuan dual origin (PR 6A parcial) | #215, merge `86596d03` | Vistas/GLB a `AssetInput` |
| Labs CHR/STY (PR 7) | #218, merge `70854428` | Personajes, Series, Story, cómics. CHR-05 excepción; Director no |
| Tools 6A remainder | #217, merge `5b4e6334` | TLS-01..05 |
| InputsPanel dual origin | #223, merge `ef5b0871` | IMG-01..04, VID-01..06, AUD-01 en Frames. Superficies duplicadas no |
| Router Story Music | #426 | HTTP en `app/routers/story_music.py`; no reextraer |
| Sesión Story Lab | #428 | Recuperación/CAS en el módulo de sesión |
| Slice musical Studio | #430 | `studioMusicSlice.ts`; no extraer todo startGeneration |
| Locks Director | #427 | Claim/delete extraídos |
| Reconcile/observer Director | #431 | No es un PipelineRuntime completo |
| Concurrencia Wizard | #429 | Un efecto por paso concurrente; F8 no certificada |
| GenerationRecord Story Music | #432 | Proyección CAS; Activity/Library no son lectores universales |
| Policy H3 desde Studio | #433 | El request efectivo proyecta la policy |
| Identidad plano cómic | #434 | Fingerprint PRE extraído |
| Contratos prompt H3 story-video | #435 | No rehacer el adapter |
| Candidato H3 validado | #436 | Parse/validación extraídos |
| Routers HTTP Series / Character Kit / Story library | #437, #438, #441 | Comparten el runtime core |
| Plan de reparación pipeline | #439, #440 | Persistencia de estado de repair |
| YuE2 + AuK (WanGP 13.00) | #421 | [WANGP_1300_AUDIO](WANGP_1300_AUDIO.md); no es QA de AuK Base/ES |
| Voces de personaje grabadas | #417 | `qwen3_tts_base` + muestra 3–30 s |
| Qwen Image 2.1 (+ GGUF uncensored) | #448, #453, #457 | T2I+edit unificado; sin gate Mature Mode en GGUF uncensored |
| Intents Image Studio / local-edit / Auto | #455 | [image-studio/HOWUSEIT](../image-studio/HOWUSEIT.md) |
| H3 experimental 30 s | #450 | Opt-in 719 frames; catálogo sigue en 345 |

La integración es en **development**. No implica que el servidor local esté usando
esa revisión ni que exista una publicación de aplicación en main.

## En curso al comprobarlo

Las reservas siguientes son la fotografía del 07/09. Reconsultar PRs abiertos
antes de tratarlas como activas: Image Studio ya tiene intents propios (#455)
y varios consumidores pasaron a `AssetInput`.

Al cerrar la revisión del 07/09 el taller de habla (#200), la limpieza documental
(#199) y el contrato attemptId (#201) ya están integrados. Escenas 3D reales
(#198) se mezcló en development el 07/09 (`fae7d3f6`). Estado por dominio:

- **Selector universal de recursos (edit Studio)**: IMG-05..09 y IMG-16 a
  `AssetInput` (`StudioSourceField`). Rama `feat/asset-picker-6a-images`, PR
  #224. No tocar Inpaint/Outpaint/EditAnything/Blend/Retake ni
  `StudioSourceField.tsx`. Restan IMG-10..15 (Recast/Restyle/Panorama),
  superficies duplicadas de Studio, 6B, Scene3DWorkspace y PR 8 Wizard.
  No mezclar hasta que lo pidan.
- **Vídeo procedural**: conservar el checkpoint `work/procedural-video-pilot-checkpoint`;
  consultar [PROCEDURAL_VIDEO_ROADMAP](PROCEDURAL_VIDEO_ROADMAP.md) y el documento del
  subdominio asignado. No mezclar el checkpoint en bloque ni asumir que todo su
  historial está pendiente.

«En curso» se basa en rama y diff, no en inferir que un agente siga conectado.
No limpiar estos worktrees, stashes, archivos sin seguimiento ni outputs. El estado
local y sus rutas de máquina se mantienen fuera de Git en `ESTADO_LOCAL.md`.

## Pendiente: refactor y validación

Los cortes G01–G14 de Story Music, sesión Story, slice musical, Director
(locks/reconcile), Wizard concurrente, GenerationRecord de canción, policy H3
y routers de librería **ya están integrados** (tabla de arriba). No
volver a extraerlos.

1. **Director siguiente**: no existe todavía un `PipelineRuntime` tipado
   completo. Ciclo de vida y dependencias tipadas siguen abiertos; no mover
   helpers que mezclen I/O con generación.
2. **Trazabilidad**: Story Music proyecta GenerationRecord. Studio
   image/video, Tools, Activity y Library **no** son lectores universales.
   Conservar una proyección y la autoridad de TaskRegistry/asset-manifest.
3. **Labs, cierre de validación**: `attemptId` vs número de plano está en #201.
   Siguen navegación móvil real, prueba audiovisual acotada y equivalencia
   UI/Wizard más amplia. #196 no repitió GPU.
4. **Producto separado del refactor**: fidelidad de letras/idioma (el guard
   ya corre en Story Music y `prepare_studio_music`) y evaluación real de
   Creative/audio H3 y del pase experimental de 30 s. Sin repetir matrices
   masivas ni inventar resultados.
5. **Entrega**: `main` permanece detrás de development. Reconsultar
   protecciones y preparar una release solo dentro de su autorización. Esta
   limpieza documental no publica ni cambia reglas de GitHub.

Orden recomendado: terminar los cambios locales ya empezados, cerrar lagunas de
validación y abordar un único contrato de refactor por PR. Detalle de ownership y
priorización en [SLICE_QUEUE](SLICE_QUEUE.md).

## Contratos: consultar por tarea

| Tarea | Referencia |
|---|---|
| Instalación Windows/Linux y aislamiento de motores | [RUNTIME_PROFILES](RUNTIME_PROFILES.md) |
| Capas y dependencias | [ARCHITECTURE_FOUNDATION](ARCHITECTURE_FOUNDATION.md), [ARCHITECTURE_MAP](ARCHITECTURE_MAP.md) |
| Studio Image intents / Qwen 2.1 | [IMAGE_COMMANDS](IMAGE_COMMANDS.md), [image-studio/HOWUSEIT](../image-studio/HOWUSEIT.md) |
| H3 30 s experimental | [H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md) |
| Planos Video 3D, animaciones y revisión | [VIDEO3D_SHOT_REVIEW](VIDEO3D_SHOT_REVIEW.md) |
| Identidad y procedencia | [DOMAIN_MODEL_AND_ASSET_PROVENANCE](DOMAIN_MODEL_AND_ASSET_PROVENANCE.md), [GENERATION_RECORD](GENERATION_RECORD.md) |
| Música | [MUSIC_SUBMISSION](MUSIC_SUBMISSION.md), [MUSIC_FINALIZATION](MUSIC_FINALIZATION.md), [MUSIC_MODEL_CONTRACT](MUSIC_MODEL_CONTRACT.md) |
| Wizard | [WIZARD_ACTION_RUNNER](WIZARD_ACTION_RUNNER.md), [WIZARD_WORKFLOW_RUNTIME](WIZARD_WORKFLOW_RUNTIME.md) |
| Labs | [LABS_WIZARD_ACTION_MATRIX](LABS_WIZARD_ACTION_MATRIX.md): referencia detallada/fixture, no checklist de inicio |
| Calidad y textos | [CODE_HEALTH](CODE_HEALTH.md), [INTERNATIONALIZATION](INTERNATIONALIZATION.md), [LOCAL_VALIDATION](LOCAL_VALIDATION.md) |

## Cómo mantener este estado sin volver a crear una biblia

Al integrar un contrato, mueve su pendiente a «Integrado» con PR y límite de
validación. Retira la entrada temporal de «En curso». Si la tabla crece demasiado,
resume por dominio y deja el historial de commits en Git; no pegues conversaciones.
Los handoffs caducan al integrarse o ser sustituidos. Conserva decisiones y evidencia
en el archivo, pero no su autoridad operativa. Una fecha antigua por sí sola no
convierte un contrato técnico vigente en material descartable.
