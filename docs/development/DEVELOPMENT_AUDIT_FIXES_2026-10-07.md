# Correcciones de la revisión de development frente a main

Este documento describe el alcance del PR contra `development`; no certifica un merge ni una revisión independiente.
La revisión final de Claude queda pendiente. La rama parte de `8f3a0d75` e incorpora `development` hasta `36de8526`, incluido su inspector de planos, en un worktree aislado.

## Comportamientos corregidos

| Punto | Cambio concreto | Evidencia de regresión |
|---|---|---|
| 1 · CI de publicación | Compara el analizador, su grafo de dependencias y los paquetes con scripts de instalación; permite retirar tipos ajenos a la medición. Los límites y los checkpoints históricos se conservan. | `tests/test_code_health.py` |
| 2 · Guardado de aprobación | Reserva la cola antes del primer `await`, captura workspace/proyecto y descarta respuestas anteriores a la edición actual. | `ui/tests/seriesReviewConcurrency.test.ts` |
| 3 · Notas | Conserva el borrador por workspace, serie, episodio, plano y etapa; serializa guardados incluso entre remontajes. Sólo elimina la versión confirmada. | `ui/tests/seriesApprovalNotesRecovery.test.tsx` |
| 4 · Sondeo de renders | Los resultados de consultas y acciones antiguas no cambian el trabajo del episodio actual. | `ui/tests/seriesApprovalRenderScope.test.tsx` |
| 5 · Pausas | `pauseBefore` participa en la identidad del render cuando afecta al audio; el caso sin pausa conserva su identidad anterior. | `tests/test_series_script_produce.py` |
| 6 · Previews de vídeo | Los vídeos importados/generados aprobados se promueven también sin foley. Si tienen foley, se prepara para el take y prompt actuales; cambiar el volumen reutiliza ese sonido. | `tests/test_series_video_produce.py` |
| 7 · Finalización | Relee el checkpoint de un worker terminado antes de marcarlo interrumpido. | `tests/test_series_native_render.py` |
| 8 · Publicación de assets | Un fallo de sidecar o journal restaura el medio y metadatos anteriores, o retira la creación fallida; permite reintentar la misma intención. | `tests/test_assets_upload.py` |
| 9 · Multimedia concurrente | Serializa la misma intención entre hilos y procesos; reserva el nombre y publica medio/sidecar con un bloqueo compartido. | `tests/test_production_media_concurrency.py` |
| 10 · Wizard | Propaga `commandId` como intención y registra el archivo resultante en Activity. Rechaza destinos distintos del workspace del comando; admite `source_workspace` de importación. | `ui/tests/mediaToolWizard.test.ts` |
| 11 · Contexto interno | Una cabecera HTTP no convierte una llamada externa en interna. Production usa LocalMcp con contexto propio; las ediciones bloqueantes se ejecutan fuera del event loop. | `tests/test_agent_activity.py`, `tests/test_production_resume.py`, `tests/test_music_productions_router.py` |
| 12 · Core | Publica los cinco comandos multimedia CPU, la atribución de actor y la traza del Wizard. | `tests/test_core_media_parity.py` |
| 13 · Volver al plano | Restaura serie y episodio y comprueba el plano antes de navegar; informa si ya no existe. | `ui/tests/seriesShotEditBanner.test.tsx` |
| 14 · Escenas 3D mutables | El contenido del documento o plantilla personal participa en la identidad del take y de su registro, también al abrir el editor. Un retake de voz con el mismo nombre invalida renders y cues por sus bytes. | `tests/test_series_scene_inputs.py` |
| 15 · Exportaciones con alias | Guarda SHA-256, resuelve la versión conservada y declara indisponible una versión ya perdida. La URL verifica el mismo handle que va a transmitir. | `tests/test_export_receipts.py`, `tests/test_export_download_identity.py`, `tests/test_export_output_name.py` |
| 16 · GPU | La comprobación se refiere al dispositivo visible seleccionado; una GPU secundaria antigua no decide la compatibilidad de todas. | `tests/test_runtime_profiles.py` |
| 17 · Cutout | Restaura la visibilidad del marcador vacío al terminar la exportación. | `ui/tests/codeRain.test.ts` |
| 18 · Previsualización de bocas | Aborta al desmontar, vacía la cola e ignora respuestas tardías de otro contexto. | `ui/tests/flatRigMouthEditor.test.tsx` |

## Contratos y límites

- La recuperación de notas usa almacenamiento de sesión con el fallback en memoria del almacenamiento seguro. Cubre navegación, remontaje y recarga cuando el navegador permite persistir; no promete sobrevivir al cierre de sesión si el almacenamiento falla.
- Las publicaciones comparten `.media-publication.lock`. Las copias con nombre y exportaciones restauran archivos ante excepciones; esta recuperación no afirma ser una transacción resistente a apagados abruptos.
- Sólo se conserva una versión `.previous` del alias. Un receipt nuevo incluye SHA-256; si su contenido ya no está, sus referencias de descarga desaparecen. Una URL guardada devuelve HTTP 410 si el alias ya tiene otros bytes, también con peticiones Range. Los receipts históricos sin hash mantienen su comportamiento anterior: no se puede deducir retroactivamente qué bytes tenían.
- Las capas que usan un nombre estable siguen viendo la última exportación. La comprobación de versión se aplica a las URLs del receipt, mediante `sha256`, sin convertir los nombres de las capas en copias retenidas.
- No se generó contenido real ni se instaló un runtime de GPU. Las regresiones de renders usan renderizadores inyectados y codificación CPU; no prueban calidad artística ni compatibilidad real de modelos.
- El control completo frente a `main` detectó cinco incumplimientos que el bloqueo inicial ocultaba. Se extraen detección de ojos de Flat Rig, snapshots de canon y codificación de frames; se dividen dos funciones del rig y el informe de música. Se conservan APIs, seams de pruebas y límites de salud. La división general de los demás monolitos queda fuera del PR.
- En máquinas con varias GPU y orden CUDA desconocido, la capacidad se declara no verificada. No se confunden índices NVML con ordinales CUDA; un selector inexistente con inventario conocido elige Core. La comprobación de compatibilidad real corresponde al runtime instalado.

## Validación

Pruebas de regresión del backend y de UI, más los tres comandos obligatorios:

```bash
(cd ui && npm run check)
BASE_REF=origin/development bash scripts/check_code_health_pr_base.sh
python3 scripts/check_documentation_links.py
```

Los comandos de salud y documentación se ejecutan desde la raíz. La CI del HEAD y la revisión de Claude se distinguen de la implementación y de las pruebas locales.
