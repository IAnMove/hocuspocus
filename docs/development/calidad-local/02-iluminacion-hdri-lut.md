# 2/6 · Iluminación HDRI y LUT

> Hoja de ruta de calidad local (2026-10-03). Serie: [1 Render máster](01-render-master.md) ·
> **2 Iluminación HDRI y LUT** · [3 Biblioteca CC0](03-biblioteca-cc0.md) · [4 Personajes 3D](04-personajes-3d.md) ·
> [5 Sonido](05-sonido.md) · [6 Control de calidad](06-control-calidad.md)
>
> Base comprobada: `origin/development` `ce070bee`. Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).

## Objetivo

Que los modelos (GLB generados, personajes rigueados, props) reciban luz y reflejos del entorno en vez de verse planos, y
que cada vídeo tenga un "look" de color coherente entre planos mediante LUTs `.cube`. Sin GPU extra: el coste lo paga una vez
la generación del mapa de entorno.

## Qué hay hoy (comprobado en el código)

`S/` = `ui/src/features/scene3d/`.

- **Luz base** (`S/gpu.ts:566-596`):
  - un `HemisphereLight` y un `DirectionalLight` a partir de `doc.light`;
  - fondo de color plano y sombras PCFSoft (2048 al exportar, `gpu.ts:540-563`).
- **No hay iluminación por entorno.** No existe `scene.environment`, ni `PMREMGenerator`, ni `RoomEnvironment`, ni `envMap`.
  Los materiales PBR de los GLB (`MeshStandardMaterial` vía `GLTFLoader`) no tienen nada que reflejar. Por eso los metales y
  los barnices se ven apagados.
- **Tone mapping implícito.**
  - ACES solo si hay `environment`, `worldSfx` o un set de atmósfera; `NoToneMapping` en el resto (`S/cinematicRuntime.ts:133`).
  - `outputColorSpace` y `toneMappingExposure` nunca se fijan.
- **Etapa de color.**
  - Shader `GRADE` (`S/atmos/passes.ts:109-139`): temperatura, tinte, contraste, viñeta y grano fijo.
  - Corre en espacio lineal, antes del tone mapping y de `OutputPass`.
  - Solo lo usa el set clearing (`S/atmos/sets/clearing.ts:350`).
  - Ningún campo del documento controla el look.
- **Esquema** (`S/types.ts`): `Scene3DLight` solo direccional (`:227-232`), `environment` (`:261`), `atmos` (`:263`) y
  `renderLook?: 'n64'` (`:237`). No hay exposición, LUT, mapa de entorno ni grade.
- **three r183** (`ui/package.json:38`) ya trae `HDRLoader`, `EXRLoader`, `UltraHDRLoader`, `LUTCubeLoader`, `LUT3dlLoader`,
  `LUTPass` y `RoomEnvironment`. `RGBELoader` está obsoleto desde r180; hay que usar `HDRLoader`.
- **Reglas que hay que respetar** (`docs/development/ATMOS_SETS.md:376-389`): reutilizar `atmos/passes.ts` y no crear un
  segundo composer. Los sets usan emisivos como luz rebotada falsa (`:41`).

## Diseño

1. **Campos nuevos y opcionales en el documento:**
   ```ts
   lighting?: { environment: { source: 'room' | 'hdri' | 'none', asset?: string, intensity: number,
                               rotation: number, background: 'set' | 'hdri' | 'blurred', blur: number } }
   look?: { toneMapping: 'aces' | 'agx' | 'neutral', exposure: number,
            lut?: { asset: string, strength: number } }
   ```
   Un documento sin estos campos se pinta exactamente igual que hoy (mismo hash). Los documentos nuevos nacen con
   `source: 'room'`. `RoomEnvironment` no descarga nada y mejora todos los GLB al momento.
2. **Mapa de entorno.**
   - `HDRLoader` → `PMREMGenerator` → `scene.environment`, con `environmentIntensity` y `environmentRotation`, y
     `backgroundBlurriness` para el modo `blurred`.
   - El mapa se genera una sola vez por HDRI y se libera al cambiarlo.
   - Con un set de atmósfera, el cielo del set sigue siendo el fondo (`background: 'set'`). El HDRI solo aporta la luz y los
     reflejos, con una intensidad por defecto propia de cada set (`rooftopNight` baja y `desert` alta).
3. **Orden de color correcto para las LUT.** Una LUT `.cube` está pensada para imagen ya mostrada (sRGB tras el tone mapping).
   Por eso `LUTPass` va **después** de `OutputPass` y antes del pixel pass. `GRADE` se queda donde está, para no cambiar el look
   de clearing.
4. **LUTs propias y libres de licencia.** Un script genera unas 8 LUT de la casa (neutra, cálida, fría, teal-orange, noir,
   bleach bypass, vintage y noche americana) como `.cube` deterministas. El usuario puede importar las suyas: nuevo tipo de
   recurso `lut` (ver [3 Biblioteca CC0](03-biblioteca-cc0.md)).
5. **Sol alineado con el HDRI (opcional).** Se busca la región más brillante del equirectangular y desde ahí se orienta el
   `DirectionalLight`, para que las sombras coincidan con el reflejo.
6. **Servidor y cliente iguales.** El render del servidor ([1 Render máster](01-render-master.md)) carga el HDRI y la LUT desde
   la caché local por una ruta de la API, nunca desde internet.

## Fases (un PR por fase)

### Fase 1 · Contrato de color y entorno por defecto
- **Qué:**
  - Los campos `lighting` y `look` en `types.ts`, `document.ts` (parseo) y `documentValidation.ts`.
  - Fijar `outputColorSpace`, `toneMapping` y `toneMappingExposure` de forma explícita.
  - `RoomEnvironment` por defecto en los documentos nuevos.
  - Colocar el `LUTPass` en el composer, todavía sin LUT cargada.
- **Pruebas:**
  - Un documento antiguo da el mismo hash de fotograma que hoy.
  - Una esfera metálica con `room` muestra reflejos (la varianza de luminancia sube por encima de un umbral) y sin entorno no.
  - Validación de rangos: exposición entre −4 y +4 EV e intensidad entre 0 y 4.
- **Quién: Claude.** Fija el orden de color y el esquema que usan las demás fases.

### Fase 2 · HDRI
- **Qué:**
  - Cargar y liberar `HDRLoader` y PMREM, con rotación, intensidad, modos de fondo y desenfoque.
  - Un paquete inicial de 6 HDRI CC0 a 1k (unos 1-2 MB cada uno), de Poly Haven, distribuido como colección opcional
    de ejemplos (`app/resources/example_assets.json`).
- **Pruebas:** rotar 180° voltea el reflejo; `intensity 0` equivale a `none`; no hay fugas al cambiar de HDRI 20 veces (el
  número de texturas vuelve al inicial).
- **Quién:** delegable.

### Fase 3 · LUT
- **Qué:**
  - `LUTCubeLoader` + `LUTPass` con intensidad.
  - El script de las LUT de la casa.
  - Importar `.cube` de 17³, 33³ y 65³.
- **Pruebas:** una LUT identidad no cambia nada (≤ 1 LSB); con `strength 0` tampoco hay cambio; una LUT 65³ carga en menos
  de 200 ms.
- **Quién:** delegable.

### Fase 4 · Valores por set, UI y MCP
- **Qué:**
  - Intensidad de entorno y LUT recomendadas para cada uno de los 20 sets de atmósfera.
  - Un panel "Look" (entorno, exposición, LUT e intensidad) con textos en español e inglés.
  - Los mismos campos en los comandos MCP de escenas.
  - Una sección en `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md`.
- **Quién:** delegable. El usuario aprueba los looks por set.

### Fase 5 · Sol desde el HDRI
- **Qué:** orientar el `DirectionalLight` hacia el punto más brillante del HDRI, de forma opcional y por documento.
- **Prueba:** un HDRI sintético con el sol en una dirección conocida devuelve esa dirección con un error menor de 3°.
- **Quién:** delegable.

## Decisiones del usuario

Decidido el 2026-10-03:

- **Solo las escenas nuevas** nacen con la iluminación nueva (`room`) y se revisan con ella. Las escenas existentes no
  cambian salvo que el usuario lo active.
- **Aprobación artística:** los looks y la luz de cada set los aprueba el usuario.

Pendiente:

- Qué 6 HDRI forman el paquete inicial: por ejemplo estudio, exterior de día, atardecer, nublado, interior cálido y noche urbana.
- Los nombres y el carácter de las LUT de la casa.

## Riesgos

- **Memoria.** Un HDRI de 4k con PMREM ocupa mucha VRAM. En la vista previa se limita a 1k y en el máster a 2k.
- **Sets ya ajustados.** La luz del entorno puede quemar los sets pensados con emisivos. Por eso cada set lleva su
  intensidad por defecto (fase 4).
- **Pixel world y `n64`.** Mantienen `NoToneMapping` y no reciben LUT salvo que se pida.

## Fuera de alcance

Path tracing, light probes horneados por escena y HDR de salida.

## Dependencias

- La [3 Biblioteca CC0](03-biblioteca-cc0.md) amplía el catálogo de HDRI y LUT más allá del paquete inicial.
- Con supersampling, el [1 Render máster](01-render-master.md) mejora los reflejos finos que añade esta fase.
