# Contratos de ejecución y baseline histórico

El registro del 5 de septiembre dejó de ser la cola de trabajo; el estado vive en
[CHANGELOG](../../CHANGELOG.md) y en el [tablero de producción](PRODUCTION_WORK_BOARD.md).
El [original completo](../archive/2026-09-06/architecture-wave/EXECUTION_BASELINE.md)
se conserva para trazabilidad; no seguir sus órdenes de ramas ni sus estados de PR.

Autoridades que siguen vigentes:

- Tareas, eventos, espera/cancelación: TaskRegistry y cola durable.
- Story/cues/candidatos/producciones: biblioteca Story e IDs de dominio.
- Bytes y provenance publicados: asset-manifest junto al archivo.
- GenerationRecord: proyección durable con CAS; no otro scheduler o catálogo.
- `workspace_id` es colección opcional; `output_folder` es ubicación física.

Contratos detallados: [GENERATION_RECORD](GENERATION_RECORD.md) y
[DOMAIN_MODEL_AND_ASSET_PROVENANCE](DOMAIN_MODEL_AND_ASSET_PROVENANCE.md).
Las antiguas F1–F12 están archivadas; su numeración no es Labs L0–L12.
