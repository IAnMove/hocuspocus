# Plantillas procedurales con assets de Library (P00D, primer corte)

En Video3D, abrir **Plantillas · crear con mis assets de Library**. El selector
ofrece las 24 acciones del piloto, no otras 24 variantes del mismo movimiento.
La UI de este catálogo piloto está en español; no constituye una migración del
idioma de UI, de conversación o del texto literal del usuario.

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
4. Duración: 3–12 s. BPM/intensidad sólo se habilitan en recetas que usan pulsos;
   no son un generador de audio ni sincronización automática con una canción.
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

El usuario aprobó visualmente los 24 vídeos coral v1. Se publicaron aparte en
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
