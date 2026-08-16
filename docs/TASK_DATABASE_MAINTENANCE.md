# Mantenimiento seguro de la base de Activity

La base SQLite de tareas conserva el estado recuperable de Activity y un
historial acotado de eventos. Nunca borres ni compactes la única copia.

## 1. Inspección sin cambios

El dry-run crea internamente un snapshot SQLite temporal consistente. No abre
la base original en modo escritura:

```bash
app/env/bin/python app/scripts/task_db_maintenance.py \
  --workspace-dir app/outputs \
  --dry-run
```

La salida JSON indica filas actuales, bytes y cuántas tareas/eventos eliminaría
la política. Para una base histórica importante, conserva además una copia
externa antes de aplicar cualquier acción.

## 2. Aplicar retención con backup automático

```bash
app/env/bin/python app/scripts/task_db_maintenance.py \
  --workspace-dir app/outputs \
  --apply
```

Antes de migrar o borrar, el comando crea y valida un backup consistente bajo
`app/outputs/.task-db-backups/`. Después ejecuta un checkpoint WAL pasivo, que
es compatible con el backend activo. Los límites se pueden ajustar con
`--max-age-seconds`, `--keep-terminal` y `--max-events`, o mediante
`LOREFRAME_TASK_RETENTION_MAX_AGE_SECONDS`,
`LOREFRAME_TASK_RETENTION_MAX_TERMINAL_TASKS` y
`LOREFRAME_TASK_RETENTION_MAX_EVENTS`.

## 3. Compactar sólo con el backend detenido

La retención reduce filas, pero SQLite no devuelve espacio al sistema hasta
`VACUUM`. Detén por completo `start.js` desde Pinokio y entonces ejecuta:

```bash
app/env/bin/python app/scripts/task_db_maintenance.py \
  --workspace-dir app/outputs \
  --apply \
  --compact \
  --backend-stopped
```

Sin la confirmación `--backend-stopped`, el comando rechaza la compactación
antes de crear un backup o modificar la base. También aborta si el checkpoint
detecta un escritor concurrente.

## 4. Restaurar un backup

Con el backend todavía detenido:

```bash
app/env/bin/python app/scripts/task_db_maintenance.py \
  --workspace-dir app/outputs \
  --restore app/outputs/.task-db-backups/ARCHIVO.sqlite3 \
  --backend-stopped
```

El backup se valida con `PRAGMA integrity_check`; si ya existe una base, se
crea otro backup de seguridad antes del reemplazo atómico. Inicia Loreframe Lab
sólo después de que el comando confirme el resultado.
