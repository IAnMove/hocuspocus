# Plantillas procedurales con assets de Library (P00D, primer corte)

En Video3D, abrir **Plantillas · crear con mis assets de Library**. El selector
ofrece 34 de las 41 fichas de `app/shared/scene_templates.json`: las fichas
musicales, las 22 coreografías de recortes, las 6 espaciales y las postales de
documental y ciudad. Las 7 `cinema-*` no salen aquí: sus intenciones viven en la
rejilla narrativa (`ui/src/lib/sceneNarrative.ts`) y cada ficha nombra sus
gemelas en `twins`. Siguen compilando por id (MCP, recetas guardadas). La UI de
este catálogo está en español; no constituye una migración del idioma de UI, de
conversación o del texto literal del usuario.

## El modelo de fichas (2026-10-12)

El contrato es `docs/development/VIDEO2D_TEMPLATE_MODEL.md`. En el código:

- **Un solo vocabulario de slots**: `subject_1`, `subject_2`, `background`,
  `prop_1`, `prop_2`, `foreground`. Los nombres viejos se aceptan en cada entrada
  (compositor, `compileCandidateScene`, puente Node, `video2d_compile.py`) y se
  traducen una vez: `hero` → `subject_1`, `plate` → `background`, `prop` →
  `subject_2` en `cinema-two-shot` y `music-duet` (`slotAliases` de la ficha) y
  `prop_1` en las demás (`slotAliases` del catálogo). Dos nombres para el mismo
  slot fallan con `slot_alias_conflict`. Los ids de capa usan los nombres nuevos.
- **Controles**: numéricos `{min, max, default}`, de elección `{options, default}`
  y de texto `{text: true, maxLength, default}`. TypeScript
  (`templateControls.ts`) y Python (`video2d_compile._controls`) los validan igual
  (`template_bad_control`; el texto se mide en puntos de código). El flag
  `exposed` del control decide qué muestra el compositor; BPM e intensidad solo se
  activan donde `bpm.exposed` es `true` (`music-pulse`, `music-duet`, `music-orbit`).
  Un slot puede ser obligatorio solo con una elección (`requiredWhen`:
  `music-pinball` pide `prop_1` con `bouncer: prop`).
- **Alias**: 9 ids fusionados (`aliases` en el JSON) compilan su ficha con un
  preset de controles; el valor que pase quien llama gana al preset. La escena
  guarda `narrative.templateId` = la ficha y `narrative.controls.alias` = el id
  pedido.
- **Retiradas**: `trailer-teaser` y `lyric-vertical` fallan con
  `template_retired` y `use_instead` (`retired` en el JSON).
- **Cada plano se mueve**: toda ficha `music-*` tiene una capa de cámara con
  deriva lenta (`drift` 0–1, 0.5 por defecto; 0 deja el encuadre quieto). La
  deriva se suma a la cámara propia de la ficha sin perder su empuje o su pulso
  (`cameraDrift.ts`). En planos largos el movimiento conserva su velocidad: las
  coreografías cíclicas se repiten, las órbitas dan más vueltas y las cámaras de
  cine recorren hasta el doble, dentro de unos límites de encuadre.
- **Fondo en vídeo**: `background` admite `image|video` (salvo las dos postales,
  solo imagen). Un vídeo es una capa `video` en bucle (`playback.loop`); en las
  coreografías con tira (`speed-flight`, `infinite-fall`, `conveyor`) un vídeo
  sustituye a la tira. Las naves espaciales aceptan una imagen recortada o un GLB.
- **Encuadre con assets reales** (revisión del 2026-10-12): el pintor encaja cada
  imagen en una caja con la forma del cuadro (contain), así que una ficha que
  mantiene la caja dentro del cuadro mantiene dentro cualquier imagen. Así lo hacen
  el objeto de `cinema-detail` y de `music-product`, la figura de
  `music-staircase-pop` (la cámara la sigue la mitad del camino) y las naves en
  imagen de las `space-*` (una nave en imagen usa una parte de la escala de un GLB;
  en `space-broadside` cada nave cabe en su mitad, ambas se balancean, la primera
  retrocede al disparar y los disparos son un rayo largo `bolt`). Las tiras de fondo
  (`speed-flight`, `infinite-fall`, `conveyor`) tienen copias que se tocan y una de
  cada dos va en espejo (`strip.mirror`), así una placa que no es continua se
  encuentra consigo misma en cada unión. Los rótulos de `documentary-history` (fecha
  y pie abajo a la izquierda, contador arriba a la derecha) y la pancarta de
  `city-postcard` (encima de la cabeza) no tapan al sujeto centrado.
  `ui/tests/sceneTemplateFraming.test.ts` lo mide con formas reales (1:3, 1:1.9, 3:1).
- **Alfa de los recortes**: `scenes.template.compile` avisa
  `cutout_without_alpha` cuando `subject_1`, `subject_2` o `prop_1` de una
  coreografía no tienen ningún píxel transparente (se leen los píxeles del PNG; un
  JPEG no tiene alfa). Una URL remota no se descarga y no avisa.
- **Estado de revisión**: el cargador acepta `candidate` y `approved`; cualquier
  otro valor lanza. Las 41 son `approved` desde el 2026-10-12. Se aprobaron
  viendo cada render con assets reales hechos en la app:
  - recortes de Qwen Image 2.1 con `image.remove_background`;
  - fondos sin nada que debiera moverse;
  - dos bucles H3 sin costura.

  Se renderizaron las 41 fichas y las opciones de las fusionadas con
  `npm run scene:review -- --render --assets`. Cada ficha hace lo que dice su
  línea, se mantiene en cuadro y se mueve durante todo el plano. Esa revisión
  encontró y arregló cinco cosas:
  - los vídeos desaparecían del MP4 exportado desde el editor;
  - las partículas eran invisibles sobre fondos reales;
  - las tiras tenían costuras;
  - seis encuadres;
  - el tiempo límite del render de revisión.

  El dueño puede devolver una ficha a `candidate` en este JSON.

## Crear una composición nueva

1. Elegir la acción. Revisar requisitos y límites: el compositor de capas no
   tiene oclusión 3D global, colisiones ni actuación corporal de un PNG.
2. Asignar protagonista/fondo y slots adicionales desde el workspace activo.
   El selector consulta `/api/v1/assets`; no utiliza filenames como identidad ni
   mezcla ubicaciones de otros proyectos. Muestra pero bloquea metadata heredada,
   ausente o no canónica. No migra esos archivos automáticamente.
3. Usar imágenes ya generadas en Studio y guardadas en Library. En esta fase no
   hay botón de generación integrado ni recorte/alpha/anclas automático. No se
   recurre a un generador cuando falte un asset.
4. Duración: 3–12 s. BPM/intensidad sólo se habilitan en fichas que usan pulsos;
   no son un generador de audio ni sincronización automática con una canción.
   Los demás controles expuestos (deriva, cámara, atmósfera, desenlace, textos)
   aparecen debajo y llegan a `narrative.controls`.
5. Guardar el trabajo anterior y confirmar su reemplazo (incluido audio) antes
   de crear. La aplicación vuelve a consultar los IDs y bloquea desaparición,
   cambio de tipo o ubicación. Un fallo conserva el formulario, no abre otra escena.
6. Revisar la escena editable y guardarla. Para recortes estáticos, preparar una
   versión de cintura hacia arriba y ajustar manualmente el encuadre. Las anclas
   de cabeza/cintura y el contrato automático `medium = waist-up` siguen en P03/AN0.

`narrative.assets[].catalogAtAssignment` conserva assetId, workspace, ubicación,
tipo de metadata y resumen de proveedor/modelo/run/task conocido al asignar.
La metadata canónica completa sigue en Library. Es procedencia **al asignar**:
no certifica que una capa editada después conserve los mismos bytes. Tampoco
crea todavía un sceneId/shotId/run durable ni recuperación por ID tras mover el
archivo; esas garantías pertenecen a la base P01 y recuperación posterior.

## Ver o abrir la referencia original

El usuario aprobó visualmente los 24 vídeos coral v1. Siete de esos ids son hoy
alias de otra ficha (`cinema-isolation`, `music-chorus`, `music-parallax`,
`music-stage`, `music-finale`, `space-shield`, `space-explosion`); sus hashes se
conservan en `approvedReferences.ts` como registro histórico y el test del índice
comprueba que los 24 ids siguen compilando (como ficha o como alias). Se publicaron aparte en
[procedural-style-reference-v1](https://github.com/IAnMove/hocuspocus/releases/tag/procedural-style-reference-v1),
una prerelease de referencias, no una release de HocusPocus/Pinokio.

El vídeo remoto sólo carga cuando se solicita: no autoplay, un reproductor
visible, sin descargas masivas. No presume funcionamiento offline. La referencia
muestra el original SVG/GLB; los assets propios producen una versión nueva,
pendiente de revisión visual. El estado candidato histórico no se reescribe.

GitHub no permite asumir fetch CORS para estos JSON. Se descarga el JSON y se
selecciona en **Abrir JSON original verificado**. El importador comprueba longitud
y SHA-256 contra el índice de los 24 originales, después identidad/policy/schema,
y abre su snapshot exacto sin recompilar la plantilla actual. Requiere localhost
o HTTPS para WebCrypto; sin SHA-256 disponible falla explícitamente. No se añadió
un proxy arbitrario. Un JSON editado se importa, si se desea, mediante las
herramientas JSON normales del editor, no como referencia original aprobada.

Sólo el índice de hashes/tamaños está versionado en Git. Los MP4, PNG y JSON de
outputs permanecen fuera del repositorio. No sobrescribir los originales al
regenerar una demo ni afirmar que las variantes nuevas han sido aprobadas.

## QA sin modelos

- Tests de catálogo/bindings: identidad, scope, tipo, metadata, ubicación, abort,
  404, cambio durante selección, compile/serialize/parse y ausencia de generadores.
- Componentes: controles incompatibles, selección visible, reset por plantilla/
  workspace, errores y confirmación de reemplazo.
- Importador: índice de 24, vector SHA-256 conocido, tamaño y manipulación fallan.
  Los outputs publicados no se incluyen como fixtures de CI.
- Playwright con API simulada: seleccionar → editor real → guardar → reabrir,
  conservando el snapshot y las referencias. Esto no es una exportación MP4 real.
- Local: cotejar los 24 sidecars originales con el importador y probar un MP4
  publicado. Smoke de assets pintados/alpha y exportación queda separado del CI.

Pendiente: preparación y generación explícita de assets, encuadre por anclas,
promoción versionada de variantes aprobadas, P01 identidad de escena/shot/run,
recetas AN y posterior motor 3D. No declarar P00D completo sólo por este corte.

### Reflective floor and electrical arrival

The Cinema category includes `reflective-stage` and `character-materialization`.
They are native templates with editable background image, GLB, portrait screens,
spatial effects and camera. Both have an animated bundled model so a fresh example
never relies on a T-pose. Replacement models use their own selected clip; choose
its start offset for a relaxed held pose. See [cinematic spatial effects](SCENE_EFFECTS_AND_MCP.md#cinematic-spatial-effects)
for coordinates, appearance timing, lighting, reflection limits and save/export.
