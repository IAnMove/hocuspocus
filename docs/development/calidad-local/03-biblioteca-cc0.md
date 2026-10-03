# 3/6 · Biblioteca de recursos CC0

> Hoja de ruta de calidad local (2026-10-03). Serie: [1 Render máster](01-render-master.md) ·
> [2 Iluminación HDRI y LUT](02-iluminacion-hdri-lut.md) · **3 Biblioteca CC0** · [4 Personajes 3D](04-personajes-3d.md) ·
> [5 Sonido](05-sonido.md) · [6 Control de calidad](06-control-calidad.md)
>
> Base comprobada: `origin/development` `ce070bee`. Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).

## Objetivo

Que cualquier usuario pueda instalar desde la app, sin cuentas ni claves, un catálogo de recursos libres. Cada recurso
queda registrado con su procedencia y su licencia, y la app puede generar los créditos de un vídeo. El catálogo incluye:

- HDRI y materiales PBR;
- modelos y personajes ya rigueados;
- animaciones humanoides;
- efectos de sonido.

## Qué hay hoy (comprobado en el código)

- **Ejemplos opcionales**, el precedente más cercano:
  - El manifiesto fijado `app/resources/example_assets.json` tiene 939 archivos en 19 colecciones, cada uno con
    `size` y `sha256`, y zips en el release de GitHub `example-assets-v1`.
  - La caché es direccionada por contenido (`app/cache/examples/<sha256><ext>`) y se comprueba al leerla
    (`app/services/example_assets.py:36-57`).
  - La instalación la lanza siempre el usuario. Se verifican el tamaño y el sha del zip y de cada archivo, y se reemplaza de
    forma atómica (`app/services/example_collections.py:20-73`).
  - La UI está en `ui/src/features/scene3d/ExampleDownloads.tsx`.
  - **El manifiesto no tiene licencia, autor ni URL de origen.**
- **Procedencia** (`docs/development/asset-manifest-v1.schema.json`):
  - `origin` no tiene licencia ni atribución.
  - `execution.mode` ya admite `"import"` y los objetos aceptan campos extra (`additionalProperties: true`).
  - Las subidas (`app/services/assets_upload.py`) no escriben sidecar.
  - La única lista de licencias de la app está en las plantillas (`app/services/template_format.py:22`).
- **Descargas.**
  - `app/services/safe_download.py` no sirve como descargador: solo pone timeouts y progreso.
  - Los únicos descargadores con controles están en `app/services/template_community.py` (solo https, hosts permitidos,
    tope de tamaño y sha) y en `example_collections.py`.
  - Ninguno de los dos limita las redirecciones.
- **Tipos de recurso.**
  - No existen los tipos textura, material, HDRI ni LUT.
  - El audio y los modelos tienen listas de extensiones distintas según el módulo: `core_workspace.py:15-18` frente a
    `media_paths.py:15-27`.
  - Los espacios de trabajo son una carpeta plana.
- **SFX:** solo hay generación con MMAudio (`docs/development/SFX_COMMANDS.md`); no existe una biblioteca.
- **Choque posible.** El plan pausado de biblioteca de plantillas (`docs/development/TEMPLATE_LIBRARY_PLAN_2026-09-28.md`,
  PR borrador #532) prevé «packs de efectos, rótulos y fuentes con el mismo índice (`kind` en el índice ya lo prevé)».

## Fuentes (comprobado el 2026-10-03)

| Fuente | Licencia de los recursos | Acceso | Uso propuesto |
|---|---|---|---|
| [Poly Haven](https://polyhaven.com/our-api) | CC0 | API gratuita para cualquier uso, comercial incluido, con un User-Agent propio y crédito visible «Powered by Poly Haven» si se usa la API en vivo | Espejo curado de HDRI, texturas y modelos; navegación en vivo opcional |
| [Quaternius, Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html) | CC0 (la Standard tiene 45 animaciones; la [2](https://opengameart.org/content/universal-animation-library-2) trae más de 130 en la versión Pro) | Descarga en itch.io o en la web, sin API | Espejo de la versión Standard. Encaja con el importador del rig humanoide |
| Quaternius y Kenney (modelos) | CC0 | Descarga sin API | Espejo de packs elegidos |
| ambientCG | CC0 | Web y API; hay que revisar sus condiciones de API antes de usarla | Espejo curado de materiales PBR |
| [Freesound](https://freesound.org/docs/api/overview.html) | Varía por sonido (CC0, CC-BY, CC-BY-NC) | Descargar el original exige OAuth2; las vistas previas en mp3/ogg no, pero tienen pérdida | Solo sonidos CC0, curados y espejados, con el id, el autor y la URL de cada uno |

Hay que volver a revisar las condiciones de cada fuente al implementar: pueden cambiar.

## Diseño

1. **Espejo propio con el mismo mecanismo que los ejemplos.** Un manifiesto fijado con sha256 y zips en un release de GitHub.
   La instalación es verificable sin conexión, reproducible y no depende de terceros mientras se usa. CC0 permite redistribuir.
2. **La licencia es parte del manifiesto.** Cada archivo lleva:
   ```json
   {"kind": "hdri", "license": "CC0-1.0", "source": "polyhaven", "source_url": "https://...",
    "author": "...", "retrieved_at": "2026-10-03", "sha256": "..."}
   ```
   Un test hace fallar la CI si a un archivo le falta la licencia o la URL.
3. **Tipos nuevos:** `hdri`, `material` (conjunto de mapas: albedo, normal, roughness y ao), `lut`, `animation`
   (glb o bvh humanoide) y `sfx`. Se unifican las listas de extensiones en un único módulo.
4. **La biblioteca vive en la caché compartida**, direccionada por contenido. Un recurso solo se copia a un espacio de trabajo
   cuando se usa, y entonces se escribe su sidecar con `execution.mode: "import"` y el bloque de licencia.
5. **Un único descargador seguro** para la biblioteca, los ejemplos y la comunidad: solo https, hosts permitidos, sin
   redirecciones a otros hosts, tope de tamaño leyendo `limit+1` bytes y sha obligatorio. Sustituye la lógica duplicada en
   `template_community.py` y `example_collections.py`.
6. **Créditos automáticos.** Cada exportación o producción puede generar `CREDITOS.txt`, con los recursos usados, su
   licencia y su origen. Para CC0 no es obligatorio, pero es buena práctica. Para la API en vivo de Poly Haven sí es
   obligatorio.
7. **Coordinación con plantillas.** Se usa el mismo campo `kind` del índice que prevé el plan de plantillas, para no crear un
   segundo índice. Los packs de efectos, rótulos y fuentes siguen siendo de ese plan.

## Fases (un PR por fase)

### Fase 1 · Contrato y descargador seguro
- **Qué:**
  - El esquema del manifiesto de la biblioteca (tipos y licencia).
  - Los campos de licencia en `asset-manifest-v1.schema.json` y `asset_manifest.py`.
  - El descargador compartido, la estructura de la caché y la ruta que sirve los archivos.
  - La lista unificada de extensiones.
  - La nota de coordinación con el plan de plantillas.
- **Pruebas:**
  - Rechaza http, otros hosts, redirecciones a otro host, archivos que pasan del tamaño declarado y sha incorrectos.
  - Un manifiesto sin licencia hace fallar el test.
  - `example_collections` y `template_community` siguen pasando sus tests con el descargador nuevo.
- **Quién: Claude.** Es código sensible de seguridad y es el contrato que usan las fases 2 a 6 y los puntos 2, 4 y 5.

### Fase 2 · Curación y empaquetado
- **Qué:**
  - Un script reproducible que descarga la selección y la normaliza (HDRI en 1k y 2k, texturas en PNG o JPG, glb validados
    con el inspector y audio en WAV a 48 kHz).
  - Escribe el manifiesto con sha y licencia, y empaqueta los zips al estilo de `scripts/package_example_assets.py`.
- **Paquetes iniciales:**
  - 6 HDRI;
  - 12 materiales;
  - la Universal Animation Library Standard;
  - 2 packs de personajes o props;
  - 40 efectos de sonido CC0: pasos sobre 6 superficies, puertas, ambientes y golpes.
- **Quién:** delegable. El usuario aprueba la selección.

### Fase 3 · Navegador de la biblioteca en la app
- **Qué:**
  - Un panel con filtro por tipo, miniatura, insignia de licencia, instalar y quitar, y uso de disco.
  - Integración con el selector de recursos (`ui/src/features/asset-picker`) para los tipos nuevos.
  - Textos en español e inglés.
- **Quién:** delegable.

### Fase 4 · Consumidores
- **Qué:**
  - Los HDRI y las LUT llegan a [2 Iluminación](02-iluminacion-hdri-lut.md).
  - Las animaciones se añaden con un clic a un personaje rigueado. El importador existe en el PR #765.
  - Los SFX llegan a [5 Sonido](05-sonido.md).
  - Los materiales se aplican al suelo y a los props de Video 3D.
- **Aceptación:** un clip de Quaternius retargeteado sobre el pet de prueba tiene un error de extremidad menor de 5°, con la
  misma métrica que `tests/test_humanoid_retarget.py`.
- **Quién:** delegable, una vez aterrizado el PR #765.

### Fase 5 · Créditos
- **Qué:** generar `CREDITOS.txt` en la exportación, en el paquete de producción y en MCP.
- **Prueba:** una escena con 3 recursos produce exactamente 3 entradas, con su licencia.
- **Quién:** delegable.

### Fase 6 · Navegación en vivo de Poly Haven (opcional)
- **Qué:** explorar el catálogo completo por la API, con User-Agent `HocusPocus/<versión>` y el crédito visible.
- **Quién:** delegable, si el usuario lo aprueba.

## Decisiones del usuario

Decidido el 2026-10-03:

- **Todos los paquetes CC0 son opcionales.** El usuario los descarga cuando quiera, como los ejemplos opcionales de hoy. La
  app nunca los descarga sola, ni al arrancar ni al listar.

Pendiente:

- Dónde se alojan los zips (release de GitHub: 2 GB por archivo) y el presupuesto total de disco por defecto.
- Qué paquetes van primero.
- Si se activa la navegación en vivo de Poly Haven.
- Si se aceptan sonidos con licencia CC-BY, que obligan a citar al autor, o solo CC0.

## Riesgos

- **Licencias mezcladas en Freesound.** Se mitiga con el filtro CC0, guardando la prueba de cada sonido y con el test de
  manifiesto.
- **Tamaño.** Se mitiga con paquetes pequeños, la resolución de 1k por defecto y la descarga bajo demanda.
- **Choque con el plan de plantillas.** Se mitiga con un único índice con `kind` y avisando en el tablero antes de empezar.

## Fuera de alcance

Subir recursos a una comunidad pública (eso es del plan de plantillas), los marketplaces de pago y los recursos con
licencia no comercial.
