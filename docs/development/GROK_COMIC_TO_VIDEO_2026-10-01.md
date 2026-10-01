# Cómic → película y cómic → tráiler: lo que falta para que lo haga todo HocusPocus

Brief para Grok, noche del 2026-10-01. Escrito por Claude tras convertir a mano un cómic de 30 viñetas en un tráiler (ruta B)
y en una película (ruta A). Todo lo que aquí se pide sale de fallos medidos hoy, no de suposiciones.

**Frase para Grok:** «Lee `/home/ina/grok-data/GROK_COMIC_TO_VIDEO_2026-10-01.md` y haz todo lo que dice, de principio a fin,
en el orden indicado.»

---

## 0. Qué se quiere y qué pasó hoy

Objetivo del usuario: que de un cómic hecho en HocusPocus se pueda sacar, sin pasos manuales fuera de la app, (a) una **película**
(Comic Studio → pestaña Video → PRE → generar) y (b) un **tráiler** (`production.run` con `structure: "trailer"`), con control de
calidad escena a escena (aprobar, pedir cambios al LLM, rehacer solo esa escena) y con el gasto de tokens/GPU medido.

Hoy, a mano:

- **Tráiler (B):** salió, pero con un script mío para las placas 16:9, otro para el spec y una vuelta entera perdida por una
  plantilla (`trailer-slam` pinta una placa negra opaca: 6 de 17 planos salieron negros con una palabra). Los planos H3 no pueden
  arrancar desde una imagen existente, así que se regeneraron los fotogramas (7 × ~78 s) y se perdió fidelidad con el cómic.
- **Película (A):** la pestaña Video no funcionaba: el backend contestaba `400 Unknown Director workflow 'comic_movie'` y, tras
  arreglarlo, `Shot 1: silent generation requires audio_plan.timing_anchor=video`. Ambos están arreglados en el PR **#741**
  (abierto, CI pendiente). Con eso llega a «Comic PRE ready», pero el plan es malo: 30 viñetas → **7 planos, 32,3 s**, usa 18 de 30
  paneles y **omite las dos de Marte** (la película acabaría en Starship). Pedí 14 planos y salieron 7.
- **Plataforma:** `generation.image` con una resolución que no es múltiplo de 32 termina `completed` sin imagen y sin error;
  un `intent_id` rechazado queda gastado; `image_refs` con ruta de fichero se rechaza con un mensaje poco útil. Costó 20 turnos.

## 1. Reglas (leer antes de tocar nada)

1. **Instancias.** Usa solo tu instancia propia (42021). No toques el **42003** (la del usuario: sigue en el commit #521, con 111
   cambios sin commitear suyos) ni el **42017** (la de Claude). No despliegues nada en el 42003.
2. **Un bloque = un PR**, abierto como borrador el primer día con el nombre de rama indicado. No mezcles tú: espera CI verde y
   deja el PR sin merge. Cada PR actualiza `docs/development/PRODUCTION_WORK_BOARD.md` con su fila (el PR #736 de Claude lo está
   renovando; al rebasar conserva ambas aportaciones).
3. **Tests.** Cada test nuevo va registrado en `scripts/ci_test_groups.json`. Pasa `BASE_REF=origin/development
   scripts/check_code_health_pr_base.sh` y `cd ui && npm run check` si tocas UI.
4. **No escribas tests que lean el texto de `app/_launch_runtime.py`:** el repo los inventaría como «fuente frágil»
   (`tests/fixtures/architecture_wire_inventory.json`) y la CI falla. El cableado va en ≤ 5 líneas en `_launch_runtime.py`; la
   lógica, en un módulo propio con su test.
5. **`app/services/music_production.py`** (688 líneas) solo admite ganchos de ≤ 5 líneas hacia módulos nuevos.
6. **Puertas humanas.** Aprobar un PRE, aceptar planos de prueba y la aprobación artística son decisiones del usuario. Ningún bloque
   las salta ni las automatiza por defecto. El único camino de aprobación por MCP es el de E5, con la instrucción explícita del usuario
   registrada.
7. **Tokens.** Solo los medidos por el cliente del LLM (`usage`); nunca bytes de MCP convertidos. Mide y escribe la cifra en el PR.
8. **GPU.** Una sola RTX 4090 compartida: mira `nvidia-smi` antes de lanzar nada y mide **un** clip antes de un lote. Los tests
   unitarios no usan GPU (clips sintéticos, MCP simulado).
9. **Disco.** `/mnt/extras` anda justo (~31 GB libres); pon salidas grandes y worktrees extra en `/mnt/outputs` (500 GB libres).
10. **Lo que ya existe y no se rehace:** `media.options` (#724), Qwen Image 2.1 como defecto si está instalado (#722), búsqueda
    tolerante de plantillas (en #731), bloques 0/A/B/C/D de producciones (ver tablero).

## 2. Datos de partida (solo lectura)

| Qué | Dónde |
|---|---|
| Cómic americano (proyecto v2) | `/home/ina/claude-pop-data/elon-comic-us/elon.comic.json` |
| Imágenes del cómic en el 42003 (solo leer) | `/mnt/outputs/api/hocuspocus-development/app/outputs/elon-comic-us-20261001/` |
| 30 paneles Qwen (PNG) y generador | `/home/ina/claude-pop-data/elon-comic-us/{panels,story.py,gen.py,build.py,finish.py}` |
| Tráiler: placas, spec y vigilante | `/home/ina/claude-pop-data/elon-trailer/{make_plates.py,make_spec.py,spec.json,spec_v1.json,watch.py}` |
| Producción del tráiler (estado, clips, escenas) | `/mnt/outputs/hocuspocus-worktrees/claude-pop/app/outputs/elon-trailer-us-20261001/` (`trailer-us.production.json`) |
| Ruta A con navegador headless (Playwright) | `/home/ina/claude-pop-data/elon-film/{lib.mjs,film_step1.mjs,view_pre.mjs,prepare_pre.mjs}` |
| Tráiler final | `/home/ina/claude-pop-data/final/elon_musk_a_marte_trailer_americano.mp4` (http://192.168.1.87:8844/) |
| Plan del PRE (7 planos) | http://192.168.1.87:8844/elon_pre_plan.html (pipeline `189ae88c`) |
| Informe anterior de Qwen/MCP | memoria `qwen-mcp-gotchas` y `/home/ina/claude-pop-data/elon-comic/REPORT.md` |

Los scripts de Claude importan rutas de su worktree (`/mnt/extras/hocuspocus-worktrees/claude-pop/...`): **cópialos y adáptalos**,
no dependas de esas rutas.

**Medidas de partida (hoy, RTX 4090):** panel Qwen 0,9 MP a 40 pasos: 82,6 s (77,2 de denoising); retrato: ~40 s; canción ACE-Step
(2 semillas, 60 s): 72 s; fotograma Qwen de un plano H3: ~78 s; clip H3: 198 s; 17 escenas Video 2D (CPU) del tráiler v1: 461 s;
montaje: 25 s; tráiler v1 completo ≈ 41 min de producción. Sesión de Claude: ≈ $14,35 en 110 turnos (el coste lo domina releer
~530k tokens de contexto por turno, no las llamadas a HocusPocus).

## 3. Orden de la noche

1. **G1** (rápido, desbloquea a los demás) → 2. **E1, E2, E3, E4** (película) → 3. **F2, F3, F4, F5** (tráiler: arreglos) →
4. **F1, F7, F6** (tráiler: lo nuevo) → 5. **E5, E6** (control por MCP) → 6. **G2** → 7. **H** (medida y runbook).

Antes de empezar: `git fetch && git grep` de las palabras clave de cada punto, `gh pr list` y mira las ramas remotas recientes.
Revisa el estado de **#741** (Claude, arregla `comic_movie`): si su CI falla por algo suyo, corrígelo en su rama; los bloques E se
rebasan tras su merge.

---

## BLOQUE G: plataforma

### G1. `generation.image` no falla en silencio — rama `fix/generation-image-admission`
**Problema (medido):** resolución con lados no múltiplos de 32 → el trabajo termina `completed`, `output_files: []`, tarea `skipped`
en ~1 s, sin error (el bucle de tareas lo salta por `wgp.validate_task`; que la causa sea la resolución se dedujo
probando: con múltiplos de 32 funciona y sin ellos no, no se leyó el motivo exacto). Un `intent_id` de una admisión rechazada queda gastado (`intent_conflict` al
reintentar). `image_refs` con ruta de fichero se rechaza con «reference must be a canonical local asset URL or asset ID».
**Hacer:** (1) validar la resolución en la admisión (rechazo `invalid_resolution` con la sugerencia más cercana válida, o redondeo
declarado en el recibo); (2) un trabajo cuya tarea acaba `skipped` pasa a `failed` con `error` legible, nunca `completed`; (3) no
registrar en el journal el `intent_id` de una admisión rechazada; (4) el mensaje de `image_refs` debe decir que se espera
`/api/v1/uploads/<nombre>` o un id de asset, y aceptar el nombre de un fichero del workspace.
**Archivos:** `app/services/image_generation_spec.py`, `image_generation_commands.py`; la lógica del bucle de tareas, en módulo
nuevo con ≤ 5 líneas de gancho en `_launch_runtime.py`.
**Aceptación:** tests de los cuatro casos; en vivo, `generation.image` con `1488x608` devuelve error claro y con `1504x608` genera.

### G2. `media.options` completo — rama `feat/media-options-all-kinds`
**Problema:** hoy lista solo imágenes locales; el motor de vídeo por defecto del cómic apunta a un modelo no instalado.
**Hacer:** añadir motores de vídeo instalados (con sus capacidades: I2V, primer/último fotograma, audio), música y 3D; usarlo como
fuente del defecto de E3 y de las producciones. **Archivos:** `app/services/media_options.py`, `SKILL.md`.
**Aceptación:** respuesta < 2,5 KB sin secretos; test con modelos simulados; misma prueba de ruta MCP real que ya existe.

---

## BLOQUE E: cómic → película (Comic Studio → Vídeo → PRE)

### E1. El Director respeta el cómic — rama `fix/comic-film-coverage`
**Problema (medido):** 30 viñetas, objetivo 14 planos → 7 planos / 32,3 s, 18 de 30 paneles usados. Omite los paneles 4, 5, 12–14,
16, 20, 23–25, 29 y 30 (Falcon Heavy, Dragon, Starlink y las dos de Marte). El primer paso del LLM escribió «15 timed shots» y el PRE
tiene 7: hay una segunda reducción que nadie ha explicado. `planners/comic_movie.py` ya exige un 80 % de cobertura **por bloque**
(`minimum_coverage`) y `critical_ids`, pero no hay garantía global.
**Hacer:** (1) averiguar dónde pasan de 15 a 7 (`_clip_plans_pre_polish`, `_director_segment_*`, el pulido) y documentarlo;
(2) garantizar que el primer y el último panel fuente nunca se omiten y que `target_shots` se cumple con ±1; (3) respetar los
campos del plan por viñeta del proyecto (`videoIncluded`, `videoOrder`, `durationSeconds`, `videoRenderer`) como bloqueos
explícitos, como ya dice `docs/COMIC_VIDEO_ADAPTATION.md`; (4) el PRE muestra un **informe de cobertura** (paneles usados y omitidos
y por qué) y un aviso bloqueante-con-confirmación si se omite un panel crítico.
**Archivos:** `app/services/director/planners/comic_movie.py`, el componente PRE en `ui/src/features/comics/`.
**Aceptación:** tests con respuestas de LLM simuladas (omitir el último panel ⇒ cae al plan de reserva); en vivo, el cómic de Elon
con objetivo 14 da ≥ 12 planos e incluye los paneles 29 y 30; la cobertura se reporta en el PR.

### E2. Los ajustes de la película viajan con el cómic — rama `feat/comic-film-settings-persist`
**Problema:** el motor, el objetivo de planos, el encuadre y el resto son estado de sesión. En una sesión nueva el PRE sale
«antiguo» (`Open stale PRE · rebuild before approval`) porque la huella de configuración no coincide, y queda bloqueado.
La clave es `maestro-comic-preflight:<workspace>:<project.id>` en `localStorage`.
**Hacer:** guardar esos ajustes dentro del proyecto (`ComicProject`, p. ej. `director.film`), con migración en
`normalizeComicProject`, y que la huella la calcule y devuelva el servidor. Abrir un PRE no depende de `localStorage`.
**Archivos:** `ui/src/features/comics/{ComicWorkflowPanels.tsx,store.ts,types.ts,model.ts}`, `app/services/director_pipeline.py`
(`preview_fingerprint`). **Aceptación:** prueba con navegador headless en un contexto limpio: abrir el cómic, abrir el PRE ya
preparado, sin «stale»; tests de UI.

### E3. El motor por defecto es uno instalado — rama `fix/comic-film-default-engine`
**Problema:** el selector «Video engine for this movie» arranca en «H3 Legacy Quality — ConvRot · not installed» y LTX2 22B
distilled, que sí está instalado, no aparece en la lista (solo H3 First/Last Full y Pruned, H3 Fused 4-Step y modelos no
instalados). **Hacer:** averiguar por qué LTX no se ofrece (¿filtro intencionado? documentarlo), arrancar en el primer motor
instalado y compatible (fuente: G2 / `is_downloaded`), y deshabilitar los no instalados en vez de dejarlos elegibles.
**Archivos:** `ComicWorkflowPanels.tsx`, `ui/src/lib/preferredModels.ts`. **Aceptación:** test de UI con catálogo simulado; sin
elegir nada, «Prepare PRE» usa un motor instalado.

### E4. Prueba de contrato de los flujos que envía la UI — rama `test/director-ui-workflow-contract`
**Problema:** dos fallos bloqueantes solo aparecieron manejando la UI real: los tests de cómic simulan el registro de modelos o la
salida del planificador y se saltan las validaciones reales. **Hacer:** (1) un endpoint de solo lectura con los `pipeline_type`
soportados y un test de UI que compruebe que todos los `pipeline_type` que la UI envía están en esa lista; (2) un test que lleve un
`comic_movie` con salida de LLM simulada hasta `preview_ready` pasando por `_validate_director_models` y
`validate_h3_prompt_contract` **reales** (con un registro de forma realista, como `TestDirectorBackendValidation`).
**Aceptación:** el test falla en `development` sin #741 y pasa con él.

### E5. El flujo de película por MCP, con la puerta humana — rama `feat/comics-film-mcp`
**Problema:** preparar el PRE, probar, aprobar y generar solo existen en la UI; un agente no puede manejarlos y yo tuve que usar un
navegador headless. **Hacer:** comandos `comics.film.prepare` (preflight), `.status`, `.test`, `.approve`, `.generate`.
`.approve` devuelve `approval_required` salvo que reciba `approved_by: "user"` y una `note` con lo que el usuario dijo; el PRE
registra `approved_via: "mcp"`, la nota y la hora, y la UI lo muestra. Nunca aprobar por defecto.
**Archivos:** nuevo `app/services/comic_film_commands.py` (+ catálogo y manejadores con ≤ 5 líneas en `_launch_runtime.py`),
`SKILL.md`, runbook. **Aceptación:** tests con adaptadores simulados; `tools/list` lo anuncia; en vivo, en tu instancia, un cómic
llega a PRE, se prueba 1 plano, se aprueba con la nota y se genera.

### E6. Los avisos de cola no bloquean la automatización — rama `fix/queue-leftovers-prompt`
**Problema:** «Older leftovers besides the current generation» y «A generation queue can be recovered» solo ofrecen *descartar* o
*reanudar*, tapan toda la interfaz y no hay «decidir luego». **Hacer:** botón «Decidir más tarde» (sin tocar la cola) y, por HTTP,
listar y descartar los restos (`GET/POST` sobre la cola). **Aceptación:** test de UI; sin tocar la cola, la interfaz es usable.

---

## BLOQUE F: cómic → tráiler (`production.run`)

### F1. Placas 16:9 dentro de HocusPocus — rama `feat/production-plates`
**Problema:** un panel 4:3 o vertical recortado a 16:9 pierde la imagen; lo resolví con Pillow a mano.
**Hacer:** módulo `app/services/production_plates.py`: si la proporción es ≥ 1,55 se rellena (cover); si no, el panel va nítido y
con borde sobre una copia desenfocada y oscurecida de sí mismo (sombra incluida). Se aplica solo en CPU, de forma determinista, y se
activa con un campo del spec (p. ej. `style.still_fit: "plate"|"cover"|"contain"`). Referencia exacta:
`/home/ina/claude-pop-data/elon-trailer/make_plates.py`. **Aceptación:** tests de tamaño y determinismo; las placas del Elon salen
iguales a las de referencia.

### F2. Un plano H3 puede arrancar de una imagen existente — rama `feat/production-frame-image`
**Problema:** los fotogramas iniciales de H3 solo salen de un prompt (`frame_prompt` + `image()`); no hay forma de usar un panel
ya hecho. Se regeneraron 7 fotogramas (543 s) y se perdió fidelidad con el cómic.
**Hacer:** campo de plano `frame_image` (nombre de `stills` o URL duradera): se copia como fotograma inicial y **no se lanza el
trabajo de imagen**; el QA de después sigue igual; `dry_run` descuenta el tiempo y la estimación lo refleja.
**Archivos:** `production_stage_frames.py`, validación del esquema de planos. **Aceptación:** test con un `image()` simulado que
falla si se llama; en vivo, `landing` y `starship` del Elon salen del panel original.

### F3. Los textos van sobre la imagen y no tapan caras — rama `fix/trailer-titles-over-picture`
**Problema (medido):** `trailer-slam` dibuja una placa negra opaca (`box.kind: "plate", opacity: 1`) a pantalla completa. En el
tráiler v1, 6 de 17 planos salieron negros con una palabra. Tras quitar la placa, el veredicto automático sigue marcando
`text_covers_face` en 5 cortes rápidos porque el año va centrado abajo sobre caras.
**Hacer:** (1) variante «sobre imagen» de `trailer-slam` (sin placa, tamaño y posición propios) y que sea la opción por defecto
cuando el plano tiene imagen; (2) `dry_run` avisa `title_plate_covers_picture` (hoy solo existe `title_card_on_image`) para
`trailer-slam` y cualquier plantilla con placa opaca sobre un plano con imagen; (3) colocación sensible a caras: si el chequeo de
personas del review dispone de cajas, elegir arriba/abajo según dónde no hay cara.
**Archivos:** `app/services/video2d_edit_titles.py`, `production_dry_run.py`, `production_review_checks.py`.
**Aceptación:** `dry_run` sobre `spec_v1.json` avisa; sobre `spec.json` (v2) no; test de la variante.

### F4. Los planos clave no se quedan con un clip casi congelado — rama `feat/trailer-takes`
**Problema (medido):** con `max_takes: 1`, los clips `open`, `landing` y `hangar` salieron `retake r=0.0` (casi estáticos) y se
conservaron; hizo falta una segunda pasada con acciones más visibles (cada clip H3 costó 198 s).
**Hacer:** para planos H3 no cantados en `structure: "trailer"` o `quality: standard|max`, `max_takes` por defecto 2; si el
veredicto es `frozen_shot`, reintentar **una vez** con una directiva de movimiento más fuerte añadida a `action`; protección de
presupuesto (`gpu_seconds`) y registro del motivo. **Archivos:** `production_takes.py`, `production_quality.py`.
**Aceptación:** tests con QA simulado; el coste extra de GPU medido en el PR.

### F5. El clip `close` falla y el error llega cortado — rama `fix/production-clip-audio-path`
**Problema (medido):** en el tráiler, el clip H3 del último plano (`close`, ventana 52,8–56,8 s) falló 3 veces con
`Error opening '<workspace>/b887214e….wav'`: el archivo existe en `uploads/` (la guía de audio del plano) pero se busca dentro del
workspace. El motivo se corta a ~200 caracteres y esconde el resto de la ruta.
**Hacer:** reproducirlo con `/home/ina/claude-pop-data/elon-trailer/spec.json` (producción `trailer-us`, plano `close`), corregir la
resolución de la ruta (uploads frente a workspace) y dejar una prueba de regresión; ampliar el motivo guardado a ≥ 600 caracteres
y conservar el completo en el estado. **Aceptación:** regresión que falla antes y pasa después; el plano `close` genera su clip.

### F6. Voz en off y subtítulos — rama `feat/trailer-voiceover`
**Problema:** el tráiler no tiene locución; los textos del cómic salen solo como subtítulos de plantilla.
**Hacer:** etapa `voiceover` con `qwen3_tts_customvoice`/`voicedesign` (instalados en el 42003): **primero probar con una frase
en español** (no está comprobado que lo lea bien) y medirla; por cada plano, el texto del cómic pasa a una pista de `audioCues`
del montaje con la música bajada (ducking); los subtítulos se toman de los textos (metadatos, nunca incrustados en la imagen).
**Archivos:** nuevo `production_voiceover.py` + gancho corto. **Aceptación:** tráiler de 60 s con locución audible; coste de GPU
medido; `dry_run` lo estima.

### F7. `production.plan_from_comic`: de un cómic a un spec de tráiler — rama `feat/production-plan-from-comic`
**Hacer:** comando que recibe el cómic (archivo del workspace) y devuelve un spec con `structure: "trailer"`: placas (F1) como
`stills`; los planos clave como H3 con `frame_image` (F2); las cuñas con los años que aparecen en los textos (`\b(19|20)\d{2}\b`);
los textos como subtítulos; la canción instrumental con `song.duration` y `bpm`; y `treatment` a partir de la sinopsis. La
selección de paneles clave sale de la importancia (roles del plan y paneles críticos; LLM opcional) y del reparto de
`beat_plan`/`cut_lengths` de `production_structure.py`. Línea base determinista, sin LLM obligatorio.
Referencia de lo que hice a mano: `/home/ina/claude-pop-data/elon-trailer/make_spec.py`.
**Aceptación:** sobre el cómic de Elon, un solo comando reproduce un tráiler al menos tan bueno como el v2 (`dry_run` con los mismos
avisos o menos; sin planos negros), sin pasos manuales; `production.run` posterior termina `completed`.

---

## BLOQUE H: medida y documentación

### H1. Medida reproducible — rama `docs/comic-video-benchmark`
Un guion (`scripts/`) que, dado el cómic de Elon, ejecute los dos caminos en tu instancia y escriba una tabla con: segundos por fase
(canción, fotogramas, clips, escenas, montaje), clips usados, avisos de `dry_run`, veredicto de review, y **tokens medidos por el
cliente del LLM** (si hay uno en el bucle). Compara con las medidas de partida de la sección 2. Pega la tabla en el PR.

### H2. Runbook y documentación
Actualiza `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md` (tráiler desde cómic, `frame_image`, placas, locución) y
`docs/COMIC_VIDEO_ADAPTATION.md` (cobertura, ajustes persistidos, MCP). No reescribas lo ajeno: añade tu sección. Sin backticks
sobre nombres de comando que no existan (hay un test que los cruza con el catálogo).

---

## 4. Informe final (lo que debe quedar al amanecer)

Un mensaje con, por bloque: enlace del PR y estado de CI, tests añadidos, **cifras medidas** (segundos de GPU, tokens del cliente),
lo que **no** se verificó y por qué, y lo que queda pendiente. Si un punto resultó no ser un fallo, dilo con la prueba. No marques
nada como hecho si solo pasa en tests simulados: separa «probado en simulado» de «probado en la instancia».

## 5. Lo que NO hay que hacer

- Aprobar PREs, aceptar pruebas o dar por buena una escena en nombre del usuario fuera del flujo de E5.
- Tocar el 42003 o el 42017, ni desplegar.
- Tests que lean `_launch_runtime.py` (ver regla 4) o que simulen justo lo que el fallo esquivaba (E4 existe por eso).
- Cambiar el defecto de imagen/vídeo a un modelo que no esté instalado.
- Mezclar sin CI verde, o reescribir un bloque ajeno.
