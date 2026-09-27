# Segundo lote de tareas para Grok

Fecha: 27 de septiembre de 2026. Estado: **preparado; ejecución no iniciada**.
Revisor: Claude. Se ejecutan **en paralelo** al plan Video 2D
([GROK_VIDEO2D_BOOST_PLAN_2026-09-27](GROK_VIDEO2D_BOOST_PLAN_2026-09-27.md)):
son zonas de código distintas. El «plano a plano» de los montajes
([MONTAGE_SHOT_BOARD_PLAN](MONTAGE_SHOT_BOARD_PLAN.md)) lo hace Claude; no tocar
`app/services/montage_*.py` ni `MontageControls.tsx` salvo lo indicado en G3/G4.

Las **reglas 1–12 del plan Video 2D** (§3) se aplican igual: worktree aislado desde
`origin/development`, sin GPU ni proveedores, ratchet de salud, un PR en draft por
tarea, i18n es/en, parar y preguntar ante cambios incompatibles.

Orden sugerido: G1 → G2 → G3 → G4 → G5 → G6. G1 y G2 son pequeñas y urgentes.

---

## G1 — `fix(runtime)`: la huella de instalación no debe invalidar otras plataformas

**Problema real (27/9).** `app/services/runtime_profiles.py::dependency_fingerprint`
hashea `app/runtime/profiles.json` y `runtime_install.js` **enteros**. Los PR
#487–#489 cambiaron solo entradas de Windows y aun así el arranque en Linux falló
con `HOCUS_RUNTIME_FAILED` (`installation_current` → huella distinta), aunque los
paquetes de Linux no cambiaron (`runtime_verify.py --inspect` pasaba). Se
arregló a mano reescribiendo la huella del recibo `.hocus-runtime-profile.json`.

- [ ] Hashear el **JSON canónico de la receta resuelta** para `(engine, platform)`
  (`recipe(engine, platform)` con `json.dumps(sort_keys=True)`) en lugar del
  fichero completo `profiles.json`.
- [ ] `runtime_install.js`: sustituir el hash del fichero entero por una
  **versión explícita de los pasos de instalación** por motor/plataforma (p. ej.
  `installStepsVersion` en la receta) que se incrementa cuando cambian los pasos
  que afectan a ese motor. Documentarlo en el propio fichero y en `docs/`.
- [ ] Migración: un recibo con la huella antigua cuyo motor pasa
  `runtime_verify.py --inspect` se **acepta y se reescribe** con la huella nueva
  (una sola vez), en vez de exigir Install/Update.
- [ ] Tests: cambiar la entrada `win32` no cambia la huella `linux`; cambiar la
  receta `linux` sí; migración del recibo antiguo.
- Aceptación: en Linux, fusionar un cambio solo de Windows y reiniciar no pide
  reinstalar.

## G2 — `test`: arreglar los 3 tests que fallan en `development`

Fallan en `development` desde antes de #494 (confirmado en un worktree limpio):
`tests/test_director_cancellation*.py` (2) y `tests/test_download_state*.py` (1).

- [ ] Reproducir con `pytest -q <ficheros>`, diagnosticar y arreglar la causa
  (código o test), sin marcar `skip`/`xfail` salvo justificación escrita.
- [ ] Si la causa es un cambio de contrato legítimo, actualizar el test y
  explicarlo en el PR.
- Aceptación: `pytest` completo sin fallos en local.

## G3 — `feat(video-editor)`: encuadre vertical con fondo difuminado y punto focal

Hoy `_layout_filter` (`app/services/video_editor_frames.py`) solo tiene `fit`
(barras negras) y `fill` (recorte centrado). Las versiones verticales de los
videoclips se hicieron fuera de HocusPocus por eso.

- [ ] Nuevo `fit: "blur"`: fondo = el mismo clip escalado para cubrir, muy
  desenfocado y oscurecido (`boxblur`/`gblur` + `eq`), y encima el clip
  completo encajado. Parámetros opcionales por clip: `blurAmount` (0–1),
  `backgroundDim` (0–1).
- [ ] Punto focal para `fill`: `focusX`/`focusY` (0–100, por defecto 50) que
  desplaza el recorte (`crop=w:h:x:y` con expresiones acotadas).
- [ ] Contrato: añadir los campos a la exportación del Editor de vídeo
  (`app/_launch_runtime.py` + paridad en `app/routers/video_editor.py`), a
  `app/services/montage_documents.py` (`clips[]`, opcionales, con límites) y a
  `ui/src/api/montages.ts`. Montajes guardados sin esos campos se exportan igual.
- [ ] UI: selector de encuadre por clip con los tres modos y un control de punto
  focal (arrastrar sobre la miniatura).
- Tests: filtro generado por modo; export real corto con ffmpeg (`fit: blur`
  a 1080×1920 desde un clip 16:9) comprobando dimensiones; normalización del montaje.

## G4 — `feat(montages)`: derivar un montaje vertical desde uno horizontal

Depende de G3.

- [ ] Operación `montages.derive` (MCP + `POST /api/v1/montages/{file}/derive`)
  `{format: "9:16" | "1:1" | "4:5", fit: "blur" | "fill"}` → crea
  `<nombre> (9:16).montage.json` con los mismos clips (encuadre elegido, punto
  focal heredado si existe), la misma banda sonora y audios, y los overlays
  recolocados en la zona segura vertical (ancho ≤ 90 %, `y` dentro de 12–80 %).
- [ ] Guarda `derivedFrom: {file, revision}` en el montaje nuevo (campo
  opcional nuevo, solo informativo). No modifica el original.
- [ ] UI: botón «Crear versión vertical» en el Editor de vídeo cuando hay un
  montaje abierto.
- Tests: derivación, recolocación de overlays, conflicto si ya existe
  (`409 exists`, usar `file` + `expected_revision` para regenerar).
- Aceptación: derivar «The Bird Is Freed - cinematic» (workspace `x-song`) y
  exportarlo; adjuntar ruta del MP4 en el PR.

## G5 — `feat(audio)`: acortar una canción con cortes alineados al compás

Todos los videoclips deben durar < 3 min. Se hizo a mano: elegir tramos,
alinear cada corte a la misma fase rítmica (correlación de la envolvente de
onsets en ±1,6 s) y unir con microfundidos de 12 ms.

- [ ] Servicio `app/services/song_shorten.py`: dado un WAV y una lista de tramos
  `keep: [[a, b], …]` en tiempo original, (1) ajusta cada punto de corte al
  instante más parecido rítmicamente (correlación normalizada de
  `onset_strength`, ventana ±4 s, búsqueda ±1,6 s; usar librosa, que ya está en
  el entorno si lo usa `audio_analysis.py`; si no, parar y preguntar), (2) une con
  fundidos cortos, (3) devuelve el WAV nuevo y un **mapa de tiempos**
  `[[t_nuevo, t_original, duración], …]`.
- [ ] Propuesta automática: `suggest_keep(duration_max=180)` a partir de la
  estructura que ya calcula `/api/v1/audio/plan-structure` (quitar un estribillo
  repetido, acortar puentes/instrumentales), siempre revisable.
- [ ] Endpoint + MCP `audio.shorten` (CPU; nunca la cola de GPU) y un panel en
  el Editor de vídeo: «Acortar canción a < N s» con los tramos editables sobre la
  forma de onda y preescucha de cada corte.
- [ ] Si hay un montaje abierto, remapear `clips`, `overlays` y `audioCues` con
  el mapa de tiempos (lo que cae en tramos eliminados se descarta o se recorta,
  informando).
- Tests: alineación con una señal sintética de clics a BPM conocido (el corte
  cae en fase), mapa de tiempos, remapeo de un montaje.

## G6 — `feat(video-editor)`: preajustes de publicación

- [ ] Preajustes de exportación: **X** (≤ 2:20 estándar / ≤ 3:00 Premium, H.264
  High, AAC 128k), **YouTube**, **YouTube Shorts / Reels / TikTok** (9:16,
  ≤ 60/90 s), **Archivo máster**.
- [ ] Normalización de sonoridad en dos pasadas (`loudnorm`, −14 LUFS integrados,
  −1 dBTP) como opción del export, registrada en el sidecar.
- [ ] Avisos antes de exportar: duración por encima del límite, relación de
  aspecto que no encaja, texto fuera de la zona segura vertical.
- [ ] Miniatura: extraer un fotograma elegido (`extract_frame`) a PNG junto al MP4.
- Tests: construcción de argumentos por preajuste, avisos, loudnorm con un
  tono sintético (medir LUFS de salida ±1).

---

## Entregables y revisión

Como en el plan Video 2D (§4 y §7): ejemplo de contrato, validación, demo cuando
aplique, y lo que no se ha hecho. Registrar aquí el avance:

| Tarea | Rama / PR | Estado | Notas |
|---|---|---|---|
| G1 | | pendiente | |
| G2 | | pendiente | |
| G3 | | pendiente | |
| G4 | | pendiente | |
| G5 | | pendiente | |
| G6 | | pendiente | |
