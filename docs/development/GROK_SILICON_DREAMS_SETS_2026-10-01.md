# Grok: tres escenarios Video 3D "Silicon Dreams" (estética synth de los 80)

Encargo del usuario (2026-10-01): "unas escenas basadas estéticamente en Silicon Dreams". Respuestas del usuario a las tres
dudas: la referencia es **la estética synth de los 80** (retrofuturismo de silicio: rejillas, cian y magenta, circuitos, chips,
neón, fósforo de monitor), el tipo son **escenarios Video 3D reutilizables** (como el claro, la cascada, Marte o la nieve) y
la cantidad es **3**. No hay una obra concreta de referencia: el nombre es una dirección de estilo, no un decorado a copiar.
Nada de logos, marcas, texto legible ni personajes de terceros.

Esto continúa `docs/development/ATMOS_SETS.md` (sets 1-17 ya existen) y su receta "Adding a set". Léelo entero antes de empezar:
las reglas de allí mandan (todo procedural, ningún modelo ni imagen nuevos en el repo, un solo compositor, el hueco del personaje).

## Reglas de trabajo

- Worktree propio desde `origin/development`; no uses el checkout compartido `/mnt/extras/pinokio/api/hocuspocus-development`.
  No toques 42003 ni 42017; usa tu instancia o la captura de software (`npm run atmos:capture`). `nvidia-smi` antes de GPU.
- Un PR por escenario, en este orden: **grid → circuit → mainframe**. Rama `feat/atmos-silicon-<nombre>`, PR en borrador el primer
  día (es la reclamación). El grid fija el estilo: sus capturas se revisan (Claude, y el usuario si lo pide) mientras tú sigues con el
  siguiente; si la revisión pide cambios de estilo, los aplicas a los dos.
- No mezcles tus PR: los revisa Claude. Comprueba la CI del HEAD de cada PR.
- Cada PR: `cd ui && npm run check`, los tests nuevos (`ui/tests/atmos*.test.mjs`), `BASE_REF=origin/development
  scripts/check_code_health_pr_base.sh`, `python3 scripts/check_documentation_links.py`, y una sección nueva en `docs/development/ATMOS_SETS.md`
  (Set 18, 19, 20) con parámetros, qué se midió y la fecha.
- Capturas y exportaciones de revisión fuera del repo: `/home/ina/grok-data/atmos/silicon-<nombre>/`.
- Tokens y tiempos solo medidos; nada de bytes de MCP convertidos a tokens.

## Biblia de estilo (común a los tres)

**Lenguaje de formas.** El mismo que el resto de sets: low-poly de sombreado plano, geometría y texturas generadas en código. Lo
que lo hace "silicon": líneas de rejilla y alambre emisivos sobre superficies oscuras casi negras, bordes brillantes, degradados de
cielo por bandas, estrellas, un sol/luna con franjas, trazas luminosas que recorren superficies, parpadeos de LED y barridos de
escaneo. Todo emisivo se apoya en el bloom que ya existe (`atmos/passes.ts`); no crees otro compositor.

**Paletas** (cada set ofrece dos; `palette` es el parámetro del usuario):

| Nombre | Cielo / fondo | Acento 1 | Acento 2 | Suelo |
|---|---|---|---|---|
| `outrun` (magenta-cian) | `#120458` → `#7a04eb` → `#ff2a6d` | `#05d9e8` | `#ff6ec7` | `#05010f` |
| `phosphor` (verde-ámbar) | `#02110a` → `#0b3d1e` | `#33ff66` | `#ffb000` | `#010804` |
| `chrome` (azul hielo-oro) | `#01012b` → `#005678` | `#d1f7ff` | `#ffd166` | `#02020a` |

**Movimiento.** Todo es función de `seconds` y de la semilla del set (determinista: el mismo fotograma sale igual en la vista
previa y en la exportación). Pulsos a un compás de 120 BPM cuando haga falta (`variant` controla la intensidad, no el tempo).
Sin `Math.random()` ni `Date.now()`.

**Hueco del personaje.** Igual que los otros sets: el círculo abierto en `subject`, sobre una plataforma pequeña cuando el suelo sea
un vacío; nada de decorado dentro del círculo ni en el pasillo hacia la cámara.

**Cámara.** Dos plantillas por set, `-wide` y `-low`, 6 s a 24 fps, `camera: 'establishment'` como las demás.

**Parámetros del usuario** (los mismos nombres que el resto): `timeOfDay`, `palette`, `variant`. Cada set define sus dos valores de
`timeOfDay` y su `variant` con rango `0-8`.

**Presupuesto.** Vista previa fluida; exportación por software de `*-wide` (1280×720, 6 s) por debajo de 60 s, como los últimos sets.
Contadores `low`/`high` en la definición (instancias: una sola llamada de dibujo por tipo). Sin WebGL2, el set degrada a un cielo
y suelo planos (`fallback`) sin lanzar.

## Escenario 1: `atmos-silicon-grid` (ajuste de biblioteca `grid`)

El llano infinito de neón: un suelo de rejilla que se pierde en el horizonte, un sol enorme a franjas medio hundido, montañas de
alambre y un cielo en bandas con estrellas.

- **Suelo:** un plano de rejilla emisiva de líneas finas (shader o líneas instanciadas) sobre negro, con la rejilla que avanza hacia
  la cámara a ritmo constante (el movimiento de las líneas es una función del tiempo; el suelo no se mueve). Desvanece la rejilla
  con la distancia con la niebla del set.
- **Sol:** un disco con franjas horizontales que se estrechan hacia abajo (la banda oscura crece), gradiente `outrun` de arriba a
  abajo, recortado por el horizonte. Halo aditivo suave.
- **Montañas:** dos filas de picos low-poly de sombreado plano con aristas brillantes en alambre, la lejana más tenue.
- **Cielo:** bandas de color suavizadas, estrellas puntuales (cuenta de `moteCount`), una o dos "naves" lejanas de un solo
  triángulo emisivo con un rastro corto.
- **Plataforma:** un disco bajo de cristal oscuro con borde emisivo para el personaje.
- `timeOfDay`: `dusk` (sol alto sobre el horizonte, cielo magenta) y `night` (sol bajo y violeta, más estrellas, rejilla más viva).
  `palette`: `outrun` y `chrome`. `variant`: densidad de la rejilla y velocidad del avance.

## Escenario 2: `atmos-silicon-circuit` (ajuste `circuit`)

La ciudad a escala de placa: se ve un circuito impreso desde el suelo, con los componentes como edificios.

- **Suelo:** placa de baja luz con un entramado de pistas emisivas (líneas en ángulos de 45° y 90° que giran con codos) y puntos de
  soldadura; las pistas son una textura procedural en lienzo (como `floorTexture` en `textures.ts`) más un barrido de pulso
  que corre por ellas como una función del tiempo.
- **Edificios:** encapsulados de circuito integrado como rascacielos (prismas oscuros con patillas a los lados y una marca de
  punto en una esquina), condensadores cilíndricos como torres redondas, resistencias tumbadas como puentes, un disipador de
  aletas como una cordillera. Todo en una instancia por tipo; colocados con `scatter` en `layout.ts`, fuera del círculo del
  personaje y del pasillo.
- **Luz:** niebla baja con bloom; LED pequeños que parpadean con una semilla por componente; un haz de luz fría que cae desde un
  "cielo" de cobre oscuro.
- `timeOfDay`: `idle` (pulsos lentos) y `compute` (pulsos rápidos, más brillo). `palette`: `phosphor` y `outrun`. `variant`:
  cuántos componentes están "activos".

## Escenario 3: `atmos-silicon-mainframe` (ajuste `mainframe`)

La catedral de datos: una sala enorme de ordenador central de los 80 vista como un templo.

- **Estructura:** suelo elevado de baldosas con una rejilla tenue, filas de armarios como monolitos de caras oscuras con paneles
  de LED, pasarelas de cable por el techo que caen en festones, bobinas de cinta y unidades de disco como altares a los lados.
- **Luz:** fila de pantallas de fósforo (planos emisivos con líneas de escaneo en la geometría o en el color, sin texto legible), LED
  parpadeando por armario con una semilla, un cono de luz cenital sobre el hueco del personaje con polvo en suspensión
  (`motes`), niebla de altura teñida.
- `timeOfDay`: `idle` y `burst` (barridos de LED coordinados y pantallas más vivas). `palette`: `phosphor` y `chrome`. `variant`:
  densidad de armarios iluminados.
- **Parentesco:** el interior que usa el vídeo "THE GREMLINS HEAR VOICES v2" (un ordenador visto como catedral). Es el mismo
  universo, a otra escala.

## Cómo entra en el repo (receta de ATMOS_SETS.md, resumida)

1. `ui/src/features/scene3d/atmos/sets/silicon<Nombre>.ts` exporta un `AtmosSetDefinition`: paletas, `times`, `defaults`, `subject`,
   `templates` (`-wide` y `-low`), `build`, `fallback`. Las partes puras de la colocación en un archivo aparte
   (`siliconCircuitLayout.ts`, como `waterfallLayout.ts`) con un test determinista y de "el círculo del personaje queda libre".
2. Los ids en `atmos/registryIds.ts` (`ATMOS_SET_IDS`, `ATMOS_TEMPLATE_IDS`) y el objeto en `ATMOS_SETS` de `atmos/registry.ts`.
3. Títulos y etiquetas (`atmos.day.*`, `atmos.swatch.*`) en inglés y español en `scene3dEditor` (`npm run i18n:check`).
4. No cambies los dressings pixel, action ni citadel. No edites los sets existentes salvo para extraer algo común.

## Aceptación (por escenario)

- Tests: layout determinista y personaje libre; los dos `timeOfDay` y las dos paletas construyen sin error; los contadores
  respetan el presupuesto; `fallback` sin WebGL2 no lanza.
- Capturas con `npm run atmos:capture -- atmos-silicon-<nombre>` (las dos plantillas, los dos `timeOfDay`, las dos paletas) con y sin
  el humanoide (`--subject`), en `/home/ina/grok-data/atmos/silicon-<nombre>/`. En la descripción del PR, la lista de archivos y qué se ve.
- Exportación por software de `-wide` a 1280×720 6 s bajo 60 s, con el tiempo medido.
- Se puede usar en una producción: un spec de ejemplo con un plano `kind: "scene3d"` que nombre cada plantilla pasa `dry_run` (ver
  `production_scene3d.py` y el runbook, sección de `scene3d`). Añade ese test.
- La sección del set en `ATMOS_SETS.md` con parámetros, qué se midió y la fecha.

## Entrega

Para cada PR: enlace, qué se ve, archivos tocados, pruebas con sus números, medida de exportación, conflictos evitados y qué falta.
Al acabar los tres, un resumen final con las capturas de cada set y una propuesta de dos o tres planos de un videoclip que los usen
(sin generarlos todavía).
