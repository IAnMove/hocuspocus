# Correcciones de integración — 12/09/2026

Base: `5f68eb124146c73cef8e5aeac33204aa07f2704e` (`development`).
Rama: `fix/integration-audit-20260912`, PR #404 hacia development.
Sin merge ni publicación de la aplicación.

| Hallazgo | Comportamiento corregido | Evidencia principal |
| --- | --- | --- |
| F1: repetir una intención de imagen remota podía ejecutar otra vez al proveedor tras perder la memoria del proceso | Reclamo de despacho persistente; estados y archivos sincronizados con la tarea. Un resultado desconocido queda interrumpido y requiere una intención nueva | `test_integration_audit_regressions.py`, `test_core_runtime.py` |
| F2: abrir más de ocho documentos eliminaba borradores sin guardar | La limpieza conserva borradores distintos de su checkpoint, aunque superen el límite de caché | `integrationAuditRegressions.test.tsx`, `scene3dDocumentHistory.test.ts` |
| F3: imagen → upscale dependía de reconciliar desde el cliente | Supervisor ligado a la vida de la aplicación, recuperación al arrancar y avance serializado | `test_integration_audit_regressions.py`, `test_wizard_workflow_executor.py` |
| F4: el renderer del servidor dependía de una vista sin montar y de imports `/src/` ausentes en producción | Entrada compilada propia; monta el stage real, espera recursos, usa el bloqueo y reloj de exportación compartidos y dispone el renderer | `test_world3d_owned_render_smoke.py`, `test_world3d_export.py` |
| F5: reanudar enlazaba la tarea fallida anterior | Nueva clave de ejecución solo para reintentar una tarea fallida, cancelada o interrumpida; conserva el historial | `test_integration_audit_regressions.py` |
| F6: Generar en el inspector no enviaba nada | Adaptadores de generación, recibo visible, errores visibles y bloqueo durante el envío. Recuperar un recibo conserva la intención y no reconstruye parámetros desde metadata | `integrationAuditRegressions.test.tsx` |
| F7: exportar a 24 fps terminaba a 30 fps | Plan, número de fotogramas, renderer y MP4 mantienen 24 fps | Smoke real con 12 fotogramas, 256×144, 24 fps, 0,5 s |
| F8: revisión de producción sin integrar y acciones que simulaban éxito | Panel en Director; guardado atómico de selección, aprobación y notas; regeneración mediante el endpoint existente; exportación real de las tomas aprobadas | `test_director_review.py`, `productionReviewRuntime.test.tsx` |

Al cambiar de toma se retira su aprobación anterior. La selección actualiza
también el segmento H3 único y los outputs, sin reordenar intentos ni cambiar
sus identidades. Si guardar falla, el panel conserva la selección anterior y
muestra el error. Las notas se guardan al salir del campo.

El guardado devuelve el pipeline persistido al dashboard y refresca su selección,
tags y contadores. Una respuesta tardía no cambia la producción/workspace que se
esté viendo después de salir de la revisión. Las duraciones de comparación usan
metadata de cada archivo y, cuando están disponibles, segundos o frames/fps de
la toma; no asignan la duración planificada a todas las versiones de un plano.

## Corrección de CI y revisión de #404

El job de UI del primer HEAD (`93c99821`) terminó con el runner apagado y
134 tests cancelados. Se reprodujo un agotamiento de heap en el test de revisión
con 30 ms de latencia: `assert.equal(HTMLElement, null)` intentaba representar
el grafo DOM/React mientras esperaba el guardado. La aserción compara ahora un
booleano y el test mantiene esa latencia para ejercitar el estado pendiente.
La reproducción anterior falla con heap de 256 MiB; las 20 pruebas enfocadas
corregidas pasan con ese mismo límite.

`npm test` fija la concurrencia en dos procesos, de forma que local y CI ejecuten
la misma suite completa. No se omiten tests ni se modifican umbrales de checks.
También se corrigen los dos avisos de Bugbot: actualización del dashboard y
duración individual de las tomas, incluyendo metadata del vídeo y protección
frente a respuestas de guardado tardías.
El inventario de arquitectura registra el nuevo test del dashboard como lector
de comportamiento de la fachada pública Zustand; las entradas previas se conservan.

El codec de comandos de vídeo pasa a `ui/src/lib/videoGenerationCommand.ts`.
Wizard conserva sus exports y el inspector utiliza `ui/src/api`; ninguna
superficie nueva importa directamente `features/agent`.

El inventario de rutas añade únicamente `PUT /api/v1/director/pipelines/{pid}/review`;
se comprobó que las rutas previas y su orden relativo permanecen iguales.
Las tres suites Python nuevas están incluidas en el reparto de CI. No se
modifican baselines de calidad ni se rebajan los checks.

## Validación

- Regresiones del servidor y de UI, persistencia real en archivos/SQLite con
  proveedores simulados y pruebas de componentes montados.
- Suite completa de UI: 1720 pruebas, cero fallos, concurrencia limitada a dos
  procesos mediante `npm test` (94,99 s). TypeScript, ESLint, compilación e inventario ES/EN correctos.
- Presupuesto del bundle: entrada principal 190565 bytes gzip, límite 327680.
- Smoke explícito con Chromium y FFmpeg reales sobre `ui/dist`: carga un GLB,
  avanza su movimiento, exporta y verifica el MP4. No usa modelos ni proveedores.
- Navegador: 36 pruebas generales y cuatro de habla correctas. Estas últimas
  usan la copia de Chrome ya instalada mediante configuración local temporal,
  porque la ruta predeterminada `/opt/google/chrome/chrome` no existe aquí.
- Python completo: 3368 passed, 2 skipped (139,54 s), con
  `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m pytest -q tests --durations=5`.
- Guards de repositorio, dependencias, documentación, marca y compilación Python
  correctos. Ratchet contra la base de development correcto; sin rebajar policy.

Reproducción del smoke después de compilar la UI:

```sh
RUN_WORLD3D_RENDER_SMOKE=1 python -m pytest -q tests/test_world3d_owned_render_smoke.py
```

## Límites

- El exportador World3D del servidor mantiene el rechazo explícito de escenas
  con voz/audio; este PR no implementa su mezcla. El smoke verifica movimiento
  y carga de recursos, no calidad artística, retargeting ni lipsync.
- El inspector usa los contratos de modelos admitidos por cada endpoint. El
  contrato tipado de vídeo sigue limitado a Wan 2.1 `t2v`/`t2v_1.3B`.
- La revisión exporta la selección aprobada con el audio de esos clips; no
  reconstruye la mezcla musical completa de una producción.
- No se ha ejecutado generación de pago, inferencia con modelos ni validación
  física en macOS/Windows. Los tests simulados no equivalen a esas validaciones.
- Revisión independiente y CI remoto pertenecen al HEAD del PR; no se deducen
  de estas pruebas del implementador.
