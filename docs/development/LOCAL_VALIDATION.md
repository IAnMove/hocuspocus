# Validación local

## Antes de cada push

Ejecuta `bash scripts/validate_local.sh`. Esta rutina cubre contratos Python,
la suite UI, lint, build y E2E de navegador con API simulada. No carga modelos,
no reserva GPU y no llama a proveedores externos.

## Smoke de medios reales (sólo manual)

No se ejecuta en GitHub Actions ni forma parte de la rutina anterior. Para
generar de verdad una canción con ACE-Step local y continuar el flujo de
videoclip:

```bash
RUN_GPU_TESTS=1 \
HOCUSPOCUS_SMOKE_BASE_URL=http://127.0.0.1:42003 \
HOCUSPOCUS_SMOKE_WORKSPACE=nightly-real-ace \
HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA \
bash scripts/run_real_media_smoke.sh
```

El wrapper fuerza `RUN_EXTERNAL_PROVIDER_TESTS=0`; cualquier ejecución real
requiere la confirmación explícita. Los artefactos y tiempos deben anotarse en
`comunicaciones/review.md` (fuera de Git).

Para probar únicamente ACE-Step y no renderizar el videoclip:

```bash
NIGHTLY_MEDIA_SCOPE=song \
RUN_GPU_TESTS=1 HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA \
HOCUSPOCUS_SMOKE_BASE_URL=http://127.0.0.1:42003 \
bash scripts/run_real_media_smoke.sh
```

El valor `all` (por defecto) continúa con análisis, planificación y videoclip.
