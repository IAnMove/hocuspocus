# Limpieza de archivos intermedios

Cada espacio de trabajo guarda tres clases de ficheros. Las opciones de limpieza
se aplican por clase, nunca por carpeta.

| Clase | Ejemplos | Política |
|---|---|---|
| **Resultado** | vídeos publicados, tomas aprobadas, kits, series, escenas guardadas, capítulos | No se toca nunca de forma automática. |
| **Intermedio** | fotogramas y mezcla de una exportación (`.world3d-export/`, `.scene2d-export/`), copias que una producción pone en `uploads/`, tomas crudas de una línea de voz (`ln-…-raw0.wav`), escenas `w3d-` de trabajo | Se libera cuando el trabajo que lo creó termina; lo que deja un reinicio se libera al arrancar. |
| **Caché** | proxies de vídeo 3D, carpetas temporales del análisis de voz, miniaturas, historial de la librería de kits | Con tope: tamaño (proxies, 2 GB), antigüedad (temporales, un día) o número (historial, últimas 10 revisiones). |

## Qué se libera y cuándo (`services/workspace_cleanup.py`)

- **Exportaciones Video 2D/3D.** Al publicarse el MP4, `World3DExportService._export`
  borra `frames/` y los medios de su carpeta de *staging*; se conservan los
  `.json`/`.txt` (el `snapshot.json` dice qué se renderizó). Al arrancar,
  `prune_export_staging` hace lo mismo con cualquier exportación que no esté viva:
  completada, fallida, cancelada o desconocida para el registro. Se conserva el
  staging de tareas `queued`, `waiting_resource`, `running` e `interrupted`, y el de
  carpetas tocadas hace menos de cinco minutos.
- **Producciones (videoclips).** `Production.upload()` apunta cada copia en
  `state["uploads"]`; al completarse la producción, `release_uploads` borra las que
  ya no referencia el estado (la URL del clip que usa el paquete se queda).
- **Render nativo de series.** La toma cruda de cada intento (`-raw{n}.wav` y su
  `.meta.json`) se borra al recortarla; si un intento posterior falla, la mejor toma
  pasa a ser la grabación, así que la reanudación la reutiliza. Al arrancar,
  `release_voice_raws` quita los crudos antiguos cuya grabación recortada existe.
- **Análisis de voz (Rhubarb).** La copia del audio vive en un
  `TemporaryDirectory` y desaparece con el análisis; `sweep_temp_dirs` barre al
  arrancar las carpetas `hocuspocus-speech-*` de más de un día.
- **Historial de kits.** `write_character_kit_library` conserva las últimas
  `HISTORY_REVISIONS` (10) instantáneas `*.v{N}.json` (también la librería de Lips
  Creator).

`HOCUS_KEEP_EXPORT_STAGING=1` conserva el staging de las exportaciones para depurar.
El arranque escribe una línea `[Storage] Released … GB of intermediate files`.

## Pendiente (siguiente PR)

- Panel «Limpiar ahora» en Ajustes → Almacenamiento con vista previa por clase y
  casillas, y la herramienta MCP `storage.cleanup` con `dry_run`.
- Papelera `.trash/` por espacio de trabajo con purga por antigüedad (7 días).
- Tope de tamaño configurable para las cachés y aviso antes de una producción si
  el disco libre no llega al estimado.
