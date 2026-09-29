Grok: escenarios 3D procedurales de calidad "luz y atmósfera" para Video 3D (world3d). Lo evaluará Claude PR a PR.
Base: origin/development actual. Referencia visual: /home/ina/grok-data/refs/forest_clearing_reference.png

OBJETIVO
Un tuit enseña un claro de bosque hecho con ~3000 líneas de JS/WebGL, 100 % procedural (sin modelos ni texturas
externas): troncos entre niebla, rayos de sol, sombras moteadas de hojas sobre adoquines, hierba meciéndose, polvo y
semillas flotando, hojas desenfocadas en primer plano. Queremos llegar a esa calidad DENTRO de Video 3D, como
plantillas 3D más, para poner nuestros personajes (GLB / Character Kit) delante y que reciban la misma luz y sombra.
No copiamos su código (no lo tenemos): reproducimos el look con las técnicas de abajo.

REGLAS
1. Worktree e instancia propios. Nunca 42003 (usuario) ni 42017 (Claude).
     git worktree add /home/ina/hocuspocus-worktrees/grok-atmos origin/development
   Instancia en 42021 si necesitas servidor (mismas instrucciones de enlaces simbólicos que GROK_REMAINING_2026-09-28.md).
   Una sola GPU (RTX 4090): mira `nvidia-smi` antes de las tandas; si otro proceso usa >2 GB, espera.
   Disco /mnt/extras casi lleno: capturas y vídeos en /home/ina/grok-data/atmos/, y borra lo intermedio.
2. 100 % procedural: ni GLB, ni JPG/PNG nuevos en el repo. Texturas y ruido se generan en código (canvas 2D / shader).
3. Los personajes NO se tocan: el set solo añade escenografía, luz y atmósfera. Los slots `subject_1/subject_2/prop`
   siguen funcionando igual y proyectan/reciben sombras del set.
4. Zona compartida: la lista de plantillas integradas y su catálogo/MCP los lleva Grok (M0–M9, G3–G6), o sea tú.
   No toques el trabajo de plantillas de usuario/comunidad (draft PR #532, `.hptemplate`).
5. Presupuesto de rendimiento: 1080p24 en tiempo real en la 4090 con un personaje GLB delante; ≥ 30 fps de vista
   previa en el editor. Si un efecto cuesta más de 3 ms, ponle un nivel `quality: low|high` (low para la vista previa
   del editor, high para exportar). El export MP4 debe salir idéntico fotograma a fotograma para el mismo `seconds`
   (todo es función del tiempo y de una semilla; sin `Math.random()` ni `Date.now()`).
6. Cada PR: worktree propio, tests, `cd ui && npm run check`, `BASE_REF=origin/development
   scripts/check_code_health_pr_base.sh`, sin subir capturas grandes al repo.

DÓNDE ENCAJA (ya existe, reutilízalo)
- ui/src/features/scene3d/dressing.ts + actionSets.ts + citadelSet.ts + pixel/pixelWorldSet.ts: "dressings" = escenografía
  por id (`Scene3DDressing` en types.ts). Añade una familia nueva de ids, p. ej. `atmos-clearing`, `atmos-mist-dawn`,
  `atmos-neon-rain`, `atmos-golden-room`, `atmos-dunes`, `atmos-lab`. Sigue el patrón `isActionDressing` / `actionGroup`
  y `applyActionAtmosphere` (fondo, niebla, suelo).
- ui/src/features/scene3d/cinematicRuntime.ts: ya hay EffectComposer + UnrealBloomPass + ACESFilmic + OutputPass y un pool
  fijo de luces. Amplía esa cadena (no crees otro compositor) con los pases nuevos, activándolos solo cuando el documento
  usa un dressing atmos.
- ui/src/features/scene3d/gpu.ts: sombras (`PCFSoftShadowMap`, `applyMeshShadows`). Reutiliza; añade sombras suaves solo
  para la luz principal.
- templates.ts / templateCatalog.ts / templateIds: registro de plantillas (lo tuyo). Cada set = una o dos plantillas
  ("Claro de bosque – plano abierto", "– contraluz") con cámara suave propia (camera.ts `establishment`/`reveal`).
- softwareRender.ts es el render CPU de CI (cajas y colores): no hace falta que refleje el look, pero el set debe
  degradar sin lanzar (sin WebGL2 → set simple con niebla lineal y luz plana).

MÓDULO COMPARTIDO (lo primero, ~60 % del efecto): ui/src/features/scene3d/atmos/
1. `volumetric.ts` — luz volumétrica barata. Dos opciones, elige y justifica en el PR con medidas:
   (a) pase de "god rays" en pantalla (radial blur del buffer de luminancia desde la posición proyectada del sol,
       con máscara de oclusión por profundidad), o
   (b) march de rayos en un pase a media resolución contra el shadow map de la luz direccional, 24–32 pasos con
       jitter de blue-noise y dispersión Henyey-Greenstein (g≈0.6), mezclado con la niebla.
   Recomendado (b) con niebla de altura exponencial (densidad baja arriba, más espesa al suelo) y parámetros
   `sunAzimuth`, `sunElevation`, `shaftStrength`, `fogDensity`, `fogHeight`, `fogColor`.
2. `wind.ts` — un solo campo de viento (dos octavas de ruido, dirección + ráfagas) que leen la hierba, las hojas
   colgantes y las partículas. Parámetros: `windSpeed`, `gust`.
3. `foliageShadows.ts` — sombras moteadas del dosel: proyecta una máscara procedural de hojas (ruido celular
   umbralizado, animado con el viento) como `map` de la luz o `cookie`. El suelo debe verse con manchas de sol
   móviles, como en la imagen.
4. `instances.ts` — InstancedMesh con LOD y semilla: hierba (cuchillas con curvatura y gradiente base→punta, mecidas
   en el vertex shader), hojas caídas, flores. Presupuesto: 20–60 k cuchillas, 1 draw call.
5. `particles.ts` — polvo/pólen/semillas/chispas: THREE.Points o instancias con brillo en los rayos de luz (más
   brillantes cuando están dentro del haz), tamaño con profundidad. Parámetros: `motes` (0–1), `mote size`.
6. `dof.ts` — profundidad de campo por pase (BokehPass de three/addons o gaussian ponderado por CoC) con foco
   heredado del personaje (distancia al slot `subject_1`) o fijo. Hojas de primer plano fuera de foco.
7. `grade.ts` — corrección de color cálida/fría, viñeta suave, grano fino, bloom bajo (`bloom` existente) y un toque
   de aberración cromática opcional. Un LUT procedural de 3 controles: temperatura, tinte, contraste.
8. `terrain.ts` — suelo con relieve suave por ruido + material procedural: adoquines/piedra con normal map generada
   en canvas (voronoi + bisel), musgo entre juntas, hojarasca. Que reciba las sombras moteadas.
9. `sky.ts` — cielo por gradiente + sol como disco/halo en el shader de niebla, con la dirección del sol coherente
   con `volumetric`.
Todos los módulos con dispose() completo (la escena se recrea al cambiar de plantilla) y tests de: determinismo
(mismo `seconds` → mismo hash de parámetros/posiciones), dispose (sin fugas de geometrías/materiales), degradación.

SET 1 — "Claro de bosque" (`atmos-clearing`) — HAZLO PRIMERO Y ENSÉÑALO
- Troncos altos (cilindros con textura de corteza procedural y ramas cortas), separados en 3 capas de profundidad para
  paralaje y niebla progresiva; copas fuera de plano que solo aportan sombra moteada y luz filtrada.
- Sol bajo cálido entrando en diagonal; rayos volumétricos claramente visibles entre los troncos.
- Suelo de adoquines con hierba en penachos junto a las juntas, hojas caídas, una raíz o piedra grande.
- Polvo/semillas flotando en los haces, algún insecto/hoja cayendo, hojas de primer plano desenfocadas en el borde.
- Cámara: dolly suave hacia delante a altura de ojos, 6–12 s, con leve balanceo respiratorio.
- Hueco para personajes: zona libre a 2,5–4 m de cámara, ligeramente descentrada; la luz principal debe alcanzarla
  con contraluz suave, y el personaje proyecta su sombra sobre los adoquines.
- Parámetros de plantilla (los únicos que el usuario ve): `timeOfDay` (amanecer / mañana / dorada), `fogDensity`,
  `wind`, `motes`, `palette` (verde / otoño / azulada).
- Referencia de aceptación: capturas a 1080p en 3 momentos (0 s, 4 s, 8 s), con y sin personaje delante, junto a la
  imagen de referencia. Claude las revisa con ojos: luz volumétrica legible, sombras moteadas en el suelo, profundidad
  por niebla, primer plano desenfocado, sin z-fighting ni parpadeo entre fotogramas del export.

SETS SIGUIENTES (cada uno reutiliza el módulo y añade solo composición, ~300 líneas)
2. `atmos-mist-dawn`: bosque/lago con niebla baja, luz rosa-dorada al ras, agua con reflejo procedural.
3. `atmos-neon-rain`: calle de ciudad de noche, lluvia (rayas instanciadas + salpicaduras), charcos con reflejo
   (SSR barato o planar), neones con bloom, niebla de altura teñida.
4. `atmos-golden-room`: interior de tarde, ventana con rayos y polvo, motas, madera procedural, sombra de persiana.
5. `atmos-dunes`: desierto/costa al atardecer, dunas por ruido con arena que se desplaza al viento.
6. `atmos-lab`: nave/laboratorio frío, luz de emergencia pulsante, humo de suelo, paneles emisivos.
Ve set a set: no empieces el 2 hasta que Claude apruebe las capturas del 1.

ENTREGA DEL PR 1 (módulo + set 1)
- Código, tests, doc breve en docs/development/ATMOS_SETS.md (parámetros, presupuesto medido en ms por pase,
  cómo añadir un set nuevo).
- Capturas en /home/ina/grok-data/atmos/ (NO en el repo) y un GIF/MP4 de 8 s del claro.
- Medidas: ms por fotograma (vista previa y export) con y sin personaje GLB, número de draw calls, memoria de GPU.
- Tokens de esta tarea (bytes/4 de tus respuestas de herramientas) y qué habrías necesitado que HocusPocus tuviera.

NO HACER
- No copiar ni pegar código de terceros ni del tuit; técnicas estándar, código propio.
- No añadir dependencias npm (three ya trae EffectComposer, BokehPass, Sky, etc. en three/addons).
- No cambiar el comportamiento de los dressings existentes (pixel-*, action-*, citadel…): sus tests deben seguir verdes.
- Sin audio en este PR (soundfx procedural = tarea aparte, después).
