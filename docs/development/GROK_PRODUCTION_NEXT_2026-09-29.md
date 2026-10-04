REPARTO Y ESTADO ACTUAL: ver docs/development/PRODUCTION_WORK_BOARD.md y el detalle de Grok en docs/development/GROK_PRODUCTION_BLOCKS_2026-09-30.md (tablero con dueños, ramas y archivos exclusivos; manda sobre esta cabecera).

ESTADO A 2026-09-30 (comprobado contra origin/development; el resto del documento es el plan original)
Hecho y mezclado: P0 1-5 completo (#624: panel Music productions, production.shot.use_take, production.shot.update,
production.song.use, production.cancel); 24 en su primera versión (#620/#622/#626: kind scene3d exportado con el worker de
World3D); evaluación offline del paquete antes de publicar (#619, parte de 27/28); #608, #613, #614 (ver abajo).
Pendiente de prueba real: use_take con dos tomas y GPU en una instancia (el PR #624 lo deja anotado).
Sin empezar (no aparecen en el código): 6-11, 12-16, 21-23, 25-31 y lo que falte de 24 (motor por plano con una sola paleta).
Antes de tomar un punto, comprueba con gh y git grep que nadie lo tiene.

Grok: siguiente tanda de producción de videoclips (mejoras que salieron de hacer "THE GREMLINS HEAR VOICES v2" y de revisar
#599/#602/#605). Un solo PR contra development; lo evaluará Claude.

ESTADO (ya en development, no lo repitas): #608 (planificador, revisión cacheada, auto-resume opt-in, already_running,
reintento de frames, motion en dry_run), #613 (paquete editable: scene.json por plano, orígenes en el montaje, shots.json,
tomas conservadas, production.run {package:true}, botón "Abrir escena"), #614 (quality draft|standard|max, clips guardados
al llegar, frames_sheet, cast[].group con letterbox, "Only this character appears", dymo legible, dry_run con preset).
Léelos: docs/agents/VIDEO_PRODUCTION_RUNBOOK.md y docs/development/PRODUCTION_QUALITY_ANALYSIS_2026-09-29.md.

REGLAS (las de siempre)
- Worktree propio desde origin/development; instancia propia (42021), nunca 42003 ni 42017. `nvidia-smi` antes de GPU.
- Datos grandes en /home/ina/grok-data (o /mnt/outputs); /mnt/extras casi lleno.
- Tests, `cd ui && npm run check`, `BASE_REF=origin/development scripts/check_code_health_pr_base.sh`, registrar cada test nuevo en
  scripts/ci_test_groups.json (hay un test que falla si falta). No subas medios al repo.
- Cada punto: qué falla hoy → qué hacer → dónde → criterio de aceptación (test o medida). Si un punto no cabe, márcalo
  "pendiente" en el PR y explica por qué; no lo hagas a medias.

======================================================================================================
P0 — LO IMPRESCINDIBLE PARA EL USUARIO: EDITAR PLANO A PLANO SIN SALIR DE HOCUSPOCUS
1. Panel "Producciones" (UI). Hoy no hay pantalla que liste las producciones musicales. Crea una vista que liste los
   *.production.json del workspace (status, título, duración, miniatura del montaje, botones) y, al abrir una, una
   parrilla de planos leída de <id>.shots.json: miniatura del fotograma inicial, clip, letra, sung/no, tomas con su r,
   escena. Acciones por plano: "Abrir escena" (ya existe en el Shot Board: reutiliza openSceneOutput/sceneOutput),
   "Otra toma" (production.run retake:[clave]), "Usar esta toma", "Abrir montaje". Un endpoint REST fino sobre lo que ya
   hay (production.status + shots.json); no inventes otro formato de estado.
   Aceptación: test de UI de la parrilla con un shots.json de ejemplo; en el PR, capturas.
2. "Cambiar toma y recomponer" en un clic. Hoy elegir otra toma H3 exige abrir la escena, cambiar la capa a mano,
   exportar y reemplazar el clip. Implementa `production.shot.use_take {workspace, production_id, shot, take_file}`: pone esa
   toma como clip del plano (state.clips[shot]), reconstruye el documento de escena (Production.scene_document ya existe),
   guarda revisión nueva de la escena (package), re-exporta SOLO esa escena, reemplaza el clip en el montaje (mismo
   expected_revision que usa repackage) y devuelve el nuevo vídeo del plano. Sin GPU. Dónde: services/music_production.py
   (+ un módulo nuevo production_shot_edit.py: el archivo ya es hotspot de complejidad, no lo engordes).
   Aceptación: tests con MCP simulado (el montaje termina con el clip nuevo y el origen intacto; las demás escenas no se
   re-exportan; toma inexistente → error estable) + una prueba real en tu instancia con 2 tomas.
3. "Retocar la letra/rótulo de un plano" sin abrir el editor: `production.shot.update {shot, lyric_style?, title?, camera?}`
   guarda el cambio en el spec del plano (spec.shots[i].overrides) y re-exporta solo esa escena (el fingerprint ya
   distingue). Documéntalo en el runbook como la vía para agentes; la vía humana es el punto 1.
4. Cambiar de candidata de canción. Hoy solo se guarda la ganadora. Guarda las candidatas (archivo, recall, cola) en
   state.song_candidates y añade `production.song.use {candidate}`: re-analiza (audio.analyze), recalcula ventanas y marca
   como obsoletos los clips cuyo tramo cambió (no los borres). Aceptación: test con dos candidatas; el resto de planos
   conserva su clip si su ventana de audio no cambió por más de 0,3 s.
5. `production.cancel {workspace, production_id}`: hoy no hay forma de parar una producción viva salvo matar el
   servidor. Un flag cooperativo (threading.Event por producción) comprobado entre rondas y dentro de wait(); deja el
   estado `cancelled` y reanudable. Aceptación: test con hilo real que se para en < 2 s.

======================================================================================================
P1 — CALIDAD DEL RESULTADO (lo que hizo bajar los vídeos largos y lo que falló en el Gremlins)
6. Puerta de calidad para clips NO cantados. qa.lipsync solo mide los cantados; el resto se acepta al primer intento.
   Añade services/production_clip_qa.py con medidas baratas por clip (OpenCV, sin modelos): movimiento medio y máximo,
   parpadeo (diferencia entre fotogramas consecutivos), estabilidad de color respecto al fotograma inicial y
   "salto de identidad" (histograma de color de la zona central frente al inicial). Veredicto ok|retake con umbrales y
   retoma automática por semilla dentro de max_takes (el mismo bucle de judge_take). Aceptación: tests con clips
   sintéticos (estático, parpadeante, deriva de color) y umbrales medidos en los 17 clips del Gremlins v2 (te doy la ruta).
7. Número de sujetos por plano. H3 inventó gatos junto al personaje que cantaba y Qwen dibujó al personaje 3 veces desde
   una hoja con varias vistas. Cuenta sujetos con un detector que no dependa de "persona" (p. ej. CLIP zero-shot sobre
   recortes de un detector de objetos genérico, o el propio yolox ya instalado con clase "animal/toy" si sirve; si no hay
   modelo local que valga, di qué modelo hace falta y déjalo detrás de un adaptador inyectable, como embed en
   production_review_checks). Compara con cast[].count del plano; en frames (antes de gastar clips) y en clips.
   Aceptación: adaptador + tests con detector falso; documentado qué falta para activarlo.
8. Hoja de referencia limpia por personaje. Las hojas de cast salen con varias vistas y con el fondo del set, y eso
   provoca duplicados y obliga a recortar a mano. Genera por cada cast un segundo retrato "single full-body view, plain
   neutral background, exactly one subject" (cast[].single_prompt por defecto derivado de sheet_prompt) y úsalo como
   referencia de los planos de un solo personaje; el grupo se compone con los retratos (no con las hojas). Aceptación:
   test del prompt derivado + frame_prompt; medida: 6 frames de un solo personaje sin duplicados en 6 semillas.
9. Vista previa real de la letra antes de exportar 21 escenas. Cambiar el estilo de la letra re-exporta todo (unos 45 min
   de CPU) y el validador no ve un dymo ilegible. Antes de la etapa scenes: exporta UNA escena (la de más texto), mide el
   contraste de las cajas de letra contra el fotograma real (Pillow: luminancia de la caja frente a la del texto y frente
   al fondo bajo la caja) y detén la etapa con un error claro (`caption_unreadable`, con la escena y el ratio) si < 3:1.
   Aceptación: tests con imágenes sintéticas (texto negro sobre negro → falla; crema sobre oscuro → pasa).
10. Rótulo "title-card" en planos H3. tapa el fotograma entero con una placa negra (el review lo cazó como black_bars).
   Haz que el planificador nunca ponga title-card en planos con imagen, y que validate_spec avise (no falle) si un plano
   h3/still lleva title.template == "title-card". Aceptación: test.
11. Parámetros de H3 que ya se ven: el clip de un plano largo se corta a 8 s y el resto se rellena con `fill`. Reporta en
   dry_run `hold_after_clip` (segundos que un plano quedaría sin movimiento) por plano, no solo el global.

======================================================================================================
P2 — VELOCIDAD Y COSTE (tiempo de GPU/CPU y tokens del agente)
12. Exportación de escenas en paralelo. Hoy las 21 escenas se exportan una tras otra (~1,2 min c/u). Mira el carril
   scene2d-render: si admite 2-3 trabajos concurrentes en CPU (hay 24 hilos), sube la concurrencia con un límite
   configurable (HOCUS_SCENE_EXPORT_CONCURRENCY, por defecto 2) y mide. Aceptación: tiempo de 21 escenas antes/después.
13. Progreso y ETA en production.status: clips {landed, total, eta_s} y escenas {done, total, eta_s} calculados con
   clip_seconds/timing (ya existen). Es lo que ahorra sondeos al agente.
14. Sondeo barato. production.status admite wait_s hasta 300. Sube MAX_WAIT_S a 1200 y añade `until: "stage"|"done"`
   (vuelve cuando cambia de etapa o termina). Un agente que espera 2 h con sondeos de 5 min hace 24 turnos, cada uno
   releyendo su contexto entero (medido: 126 M tokens de lectura de caché en una sesión de 333 turnos). Aceptación: test
   de wait_for_status con reloj falso.
15. Memoria de GPU entre Qwen y H3 sin reinicio manual. Hoy hay que parar en frames_ready, reiniciar la instancia y
   reanudar. Automatiza: al terminar frames, si la RAM/VRAM disponible < umbral (ya hay medida en la cola de #581), descarga
   los modelos de imagen (unload del runtime WanGP) antes de la primera cola H3. Aceptación: medida de segundos/paso de H3
   tras un frames con Qwen, con y sin la descarga.
16. Estimación de minutos con datos propios. dry_run usa 2 min/semilla y 5 min/clip fijos; guarda en un JSON del workspace
   las medianas reales por etapa (timing ya lo mide) y úsalas. Aceptación: test con timings de ejemplo.

======================================================================================================
P3 — LIMPIEZA Y DEUDA (lo que dejé anotado)
17. music_production.py es hotspot de complejidad (24 → 25). Saca a módulos: la lógica de _title_ops/_lyric_ops/_footer_ops
   (production_scene_ops.py) y la de song()/analyze() (production_song.py). Sin cambiar comportamiento: los tests actuales
   deben pasar sin tocar.
18. attach_usage guarda el estado cada 5 s; ok. Pero cada Production.save() escribe el JSON entero (spec, log, takes...)
   varias veces por minuto: separa lo volátil (log, usage) de lo estable (spec) o escribe con debounce.
19. `face_consistent` de production.review (modelo, "no" = malo) y `appearance_changed` de los chequeos de código: elimina
   la confusión de nombres en docs y, si production.review sigue sin backend de visión, decide si se retira.
20. Los presets de estilo viven en app/shared/style_presets.json. Añade un test que garantice que ningún preset
   nombra personas/proyectos (hay uno mínimo) y una guía corta de cómo añadir uno nuevo desde una producción que ya salió bien.

======================================================================================================
P1b — LO QUE APORTA LA REFLEXIÓN DE SOL (verificado contra el código; Claude la revisó el 2026-09-29)
Sol escribió esto antes de #608/#613/#614. Ya cubierto por ellos: persistencia inmediata de cada clip, hoja de fotogramas
antes de los clips, correcciones que reutilizan (fingerprint por escena), presets validados, dry_run con motion, reanudación.
Lo que sigue en pie y se confirmó en el repo (runner fija 1280x704 con H3 por defecto en 1152x640 y exporta a 1920x1080; existen
FlashVSR y RIFE en app/postprocessing y un export World3D sin navegador en services/world3d_export.py que el runner no usa;
los clips no cantados reciben "ok" sin evaluación):
21. Tratamiento y variación (arte por acontecimientos). Añade `spec.treatment` opcional: {arc, want, obstacle, moments:[{at,
    event}], motifs}. production.plan lo pide; dry_run lo usa: avisa `chorus_repeats_identical` si dos estribillos reutilizan el
    mismo plano/imagen/prompt sin variación (encuadre, consecuencia, más personajes) y `moment_without_shot` si un momento
    declarado no tiene plano en su tramo. fill[] admite variaciones (camera, crop, speed, tint) para que el relleno evolucione.
    Aceptación: tests con un spec de estribillos repetidos idénticos vs variados.
22. Montaje de prueba barato (animatic) antes de la GPU cara. `production.run {through:"animatic"}`: con los fotogramas
    iniciales como stills (kind still), la letra, los rótulos y la canción, monta un vídeo completo por CPU (unos minutos) y
    devuelve su hoja de contactos y sus avisos: tarjeta que tapa la imagen, imagen repetida, tiempo muerto (> 10 s sin
    cambio), rótulo ilegible (punto 9). Reanudar continúa con los clips reutilizando frames. Es el sitio donde habría salido
    el title-card negro del Gremlins y la "ciudad de neón" genérica de City of Windows.
23. Dos compiladores: `structure: "clip" | "trailer"`. clip = lo actual (estrofa/estribillo, cantante opcional, motivos que
    vuelven). trailer = presentación, tensión, escalada, revelación, cierre; con silencios, impactos y anticipaciones (audio:
    montage audioCues y MMAudio de app/postprocessing/mmaudio para ambientes/impactos; la canción entra tarde o no entra).
    El planificador de shots="auto" debe ramificar por structure; no reutilices la alternancia cantante/imagen/tarjeta.
24. Motor por plano (H3 / Video 2D / Video 3D). Añade kind "scene3d": referencia un .world3d.scene.json ya guardado (o una
    plantilla) + duración + cámara, se exporta con services/world3d_export.py (headless) y entra como un `clip` más (con su
    fingerprint). Mismos personajes/paleta/tiempos entre motores. Si tu PR de escenarios atmosféricos
    (GROK_ATMOSPHERE_SETS_2026-09-29.md) ya está, empieza por ahí. Video 2D: documenta y prueba los usos gráficos (riso,
    collage, diagramas, interfaces, gráficos de scene_graphics.json) para que no se reduzca a subtítulos sobre zoom.
25. Resolución de extremo a extremo. `spec.resolution` (frames e H3) y un paso opcional `enhance` que pasa cada clip por
    FlashVSR (postprocesado "flashvsr*2") antes de escalar a 1080p, con estimación de coste en dry_run; informa por plano
    resolución de origen y recorte aplicado por `fit: fill` (1280x704 → 16:9). RIFE opcional cuando el análisis de
    fluidez (26) lo pida. Mide GPU-min extra y mejora visible (SSIM/nitidez) en 3 clips del Gremlins v2.
26. Análisis de fluidez ("tirones"). En los clips, en cada escena exportada y en el vídeo final: marcas de tiempo de
    fotogramas (ffprobe), rachas de fotogramas duplicados, saltos de cadencia y cambios de velocidad; compara clip →
    escena → final para atribuir el tirón (clip original, retime, exportación). Veredicto por etapa.
27. Veredictos por niveles. production.status.review pasa a {execution, technical, artistic}: execution = el archivo existe
    y se reproduce; technical = definición, movimiento, texto, sincronía, continuidad (puntos 6-9, 26); artistic = NUNCA
    "ok" automático: devuelve las evidencias (hoja de contactos, animatic, fotogramas reales de cada momento) y queda
    "pendiente de criterio". Permite marcar intención por plano (`shot.allow: ["still","dark","secondary"]`) para que un
    plano quieto o oscuro deliberado no sea un fallo.
28. Compilar y validar TODO antes de generar. dry_run construye cada documento de escena con scenes.video2d.edit (medios
    de relleno) y valida estilos, plantillas y operaciones: los errores tipo "Text field is out of range" o "unsupported
    fields" deben salir en el dry_run, no a mitad de la exportación. Es CPU y segundos.
29. Contabilidad honesta. Quita del runbook la frase "tokens ≈ response_bytes / 4" (son bytes que leyó el ejecutor interno,
    no tokens del LLM) y renombra el bloque a `usage {mcp_calls, response_bytes, h3_takes}` sin conversión. Añade `gpu_seconds`,
    `reused_seconds` (planos que no se rehicieron) y `retry_seconds`. El coste del LLM lo mide el cliente (Claude Code guarda
    usage por mensaje); HocusPocus no debe estimarlo. Evidencia: una sesión de 333 turnos = 126,6 M tokens de lectura de caché,
    2,0 M de escritura, 0,3 M de salida (~33 $ a tarifa de Sonnet 5.5) porque el contexto medio fue de 380 k.
30. Velocidad de H3 explicada. Registra por clip las fases (carga de modelo, compilación, pasos, s/paso, exportación) y
    guárdalas en timing.shots; una lentitud de 20-38 s/paso debe atribuirse (Qwen residente, swap, plano largo) sin adivinar.
31. Publicación local dentro del flujo (bajo). `production.publish {dir}`: enlaza el vídeo, la hoja de contactos y la canción
    en un directorio servido, actualiza su index.html y comprueba los enlaces con HEAD. Hoy lo hace un script a mano.

PRIORIDAD SUGERIDA (por retorno): P0 (1-5) > 22 (animatic) + 9-10 + 28 (previsualizar y validar barato) > 6-8, 26-27
(calidad medida) > 21, 23-24 (dirección por acontecimientos y motores) > 12-16, 29-31 (operativa) > P3.

======================================================================================================
ENTREGA
- Un PR (o dos si el 1 y el 2 son grandes: P0 primero). Lista en la descripción qué puntos entran y cuáles no.
- Para cada punto de calidad (6-9): medida antes/después en una producción real (workspace gremlins-devday-v2-20260929,
  production_id voices-v2, la de Sol está en gremlins-devday-20260929/voices-in-the-wires).
- Al final: tokens de tu tarea y qué habrías necesitado que HocusPocus tuviera.
