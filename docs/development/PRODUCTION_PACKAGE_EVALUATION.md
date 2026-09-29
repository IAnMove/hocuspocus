# Evaluación offline de paquetes de producción

Este bloque es infraestructura de aceptación independiente. No modifica el
runner, los renderers, el estado de producción ni el proceso de publicación.
El agente que prepara una entrega puede ejecutarlo antes de publicar, sin servidor,
modelos, generación de medios ni GPU.

## Defecto reproducible

`Production.package()` permite continuar cuando falla el guardado del documento
editable de un plano. El manifiesto puede contener `scene_doc: null` aunque la
producción termine con `status: completed`. El test existente
`test_one_failing_shot_does_not_stop_the_package` reproduce ese comportamiento.
El estado completado y un veredicto de clip `ok` no acreditan un paquete completo
ni una aprobación artística.

El evaluador rechaza ese paquete incompleto. También detecta exportaciones
truncadas y referencias del montaje que no corresponden a los planos del
manifiesto. No cambia la política de recuperación del runner.

## Ejecutar

Requisitos: Python 3.10+ y `ffprobe` en PATH. Usar un workspace estable;
no ejecutar sobre una producción que está exportando o siendo editada.

```bash
python scripts/evaluate_production_package.py \
  --workspace-dir /ruta/al/workspace \
  --workspace-id mi-workspace \
  --production-file mi-produccion.production.json \
  > /ruta/fuera/del/repositorio/evaluacion.json
```

`--workspace-id` identifica el valor real de `?workspace=` en las referencias.
Si se omite, usa el campo `workspace` del estado cuando existe; en los estados
actuales normalmente no existe y se usa el nombre del directorio. Se recomienda
pasarlo explícitamente. No se llaman endpoints ni se copian o publican archivos.
La salida se escribe exclusivamente a stdout; la redirección es decisión del usuario.

Desde Python se puede llamar a la misma evaluación:

```python
from pathlib import Path
from scripts.evaluate_production_package import evaluate

report = evaluate(Path('/ruta/al/workspace'), 'mi-produccion.production.json',
                  workspace_id='mi-workspace')
assert report['technical']['verdict'] == 'pass'
assert report['artistic']['verdict'] == 'pending'
```

## Criterios reproducibles

Para paquetes v1 producidos por el flujo musical actual:

- Estado `completed` sin error, manifiesto, montaje, documento y vídeo por plano,
  y exportación final presentes y no vacíos.
- Versiones v1, claves de plano únicas, cobertura continua desde cero y orden de
  planos idéntico en manifiesto y montaje. Tolerancia temporal del manifiesto:
  2 ms, acorde a sus tiempos redondeados a milisegundos.
- El origen de cada clip identifica producción, plano y documento correctos.
  Su fuente identifica el vídeo del plano y el workspace correctos.
- Documento, tramo del manifiesto y trim del montaje tienen igual duración;
  los clips empiezan en cero y no usan transiciones. Montajes editados con
  transiciones quedan bloqueados como no cubiertos por este evaluador.
- `ffprobe` mide duración del **stream de vídeo**, dimensiones y FPS medio de
  cada escena y del final. Tolerancia de duración: mayor de 100 ms o dos frames
  del documento; tolerancia de FPS medio: 0,005. Una pista de audio más larga
  no puede ocultar un vídeo corto. Duración de vídeo desconocida falla.
- Si el montaje declara soundtrack, el final contiene un stream de audio.
- Nombres de archivo exactos dentro del workspace, sin rutas externas ni
  symlinks que salgan de él. JSON limitado a 10 MiB, listas a 2000 planos.
- SHA-256 y tamaño medidos en lectura incremental para los archivos inspeccionados.
  Un cambio de inode/tamaño/mtime/ctime durante la evaluación invalida el informe.

En la primera ejecución, `manifest.montage` puede ser `null` porque el paquete
se escribe antes de exportar el montaje. Es válido: se usa `state.montage_file`.
Si el manifiesto sí incluye un montaje, debe coincidir con el del estado.

## Informe y límites

`execution` comprueba cabeceras locales de vídeo; no certifica decodificación
completa. `technical` sólo cubre los criterios anteriores y enumera los aspectos
sin evaluar: decodificación completa, paridad render/snapshot, texto, movimiento,
labios, cadencia e identidad. `artistic` siempre queda `pending`.

`publication` vale `blocked` si falla un criterio y
`requires_artistic_review` si pasan todos. Nunca autoriza publicar automáticamente.
Los hashes vinculan las medidas a los archivos examinados; no autentican una
revisión independiente ni prueban que el MP4 se renderizó desde ese JSON.
Una edición o exportación posterior requiere ejecutar otra evaluación.
No se inspeccionan las fuentes de cada capa, todas las tomas históricas, la
sincronía/contenido de audio ni el aspecto de las imágenes.

Códigos de salida: `0` = pasan las comprobaciones acotadas, `1` = paquete
bloqueado/inevaluable, `2` = falta `ffprobe` o argumentos CLI inválidos.
Timeout, vídeo corrupto o medida inválida nunca son éxito. Cada probe tiene
timeout de 20 s, un hilo y protocolos `file,pipe`; no se decodifica ni renderiza.

`measurement.elapsed_seconds` es tiempo real de esta evaluación, no tiempo de
generación. No se estiman tokens del LLM ni se convierten bytes MCP en tokens.

## Propiedad y validación

Archivos de este bloque: `scripts/evaluate_production_package.py`, este documento
y los tests nuevos en `tests/test_qa_provenance.py`. Se utiliza esa suite de
procedencia ya registrada en CI para evitar una edición concurrente de
`scripts/ci_test_groups.json`. La evaluación de paquetes se distingue de la
autenticación de QA de un PR; ninguna reemplaza a la otra.

```bash
python -m pytest tests/test_qa_provenance.py tests/test_qa_evidence.py \
  tests/test_production_package.py::test_one_failing_shot_does_not_stop_the_package \
  tests/test_ci_shards.py -q
BASE_REF=origin/development scripts/check_code_health_pr_base.sh
```

Los tests usan metadatos inyectados y bytes de placeholder, sin generar vídeos,
imágenes ni audio. Un test adicional verifica que `ffprobe` real rechaza los
bytes corruptos; se omite explícitamente si esa herramienta no está instalada.
