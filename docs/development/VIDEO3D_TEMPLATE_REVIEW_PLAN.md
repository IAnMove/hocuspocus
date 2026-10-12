# Video 3D: Wizard, escenas reutilizables y revisión visual

Fecha: 2026-09-06. Base inicial: `development` en
`e795e71a2d9df6b7c24738b925622a7c0ed0a0a9` (PR #166 mezclado).

## Encargo y límites

El usuario aprobó visualmente la demo «La noche es nuestra» y pide llevar su
flujo al Wizard, una galería extensa de nuevas escenas intercambiables y abrir
los resultados en el editor. Las nuevas plantillas son **candidatas** hasta su
selección: ni un render correcto ni un PR las convierten en catálogo aprobado.

- No tocar los servicios activos 42003/42004 ni el checkout compartido.
- Trabajar desde development en un worktree propio; no publicar main.
- No ejecutar generadores neuronales de vídeo ni descargar modelos durante
  este trabajo. Render programático local y assets geométricos de muestra.
- No subir pesos ni medios generados. Sí código, contratos y documentación.
- Reutilizar el compositor real, sus keyframes, relaciones, cámara y exportador.
  No crear un renderer sustituto para que la galería parezca funcionar.
- «Sin vídeo generativo» y «sólo assets existentes» son contratos distintos.
  El prompt del LLM no puede ampliar los permisos concedidos por el usuario.
- Preservar plantillas antiguas hasta comparar resultados y recibir selección.
- No modificar Director ni `_launch_runtime.py` mientras otros agentes trabajan
  en esos hotspots. La selección automática híbrida de producciones completas
  requiere su propio contrato y PR; no se declara resuelta por esta galería.

## Preflight de esta ejecución

- [x] Releer AGENTS.md: Non-Negotiable Execution Workflow, Development Workflow,
  Troubleshooting with Logs, Best practices / Minimal / Gitignore.
- [x] Inspeccionar logs antes de diagnosticar; preservar cambios ajenos.
- [x] Leer skill Pinokio y consultar servicios sin reiniciarlos.
- [x] Confirmar base y worktree limpio antes de crear rama propia.
- [x] Sin archivos launcher: resolución de destino, ejemplos y captura URL de
  launcher no aplican a los cambios de lógica/UI de este encargo.

## PR A — Wizard y política de compositor

- [x] Inspeccionar clasificación, acción, prompt, parser, runner y resolver real.
- [x] Preservar política en la preparación Wizard y el resolver existente; el
  alcance no es un permiso global de todas las acciones del Wizard.
- [x] Impedir el atajo de vídeo generativo en peticiones explícitas de compositor;
  ante assets ausentes se conserva el preflight de recetas.
- [x] Ofrecer instrucciones concretas ES/EN y decisiones visibles para el usuario.
- [x] Tests baratos: negaciones, política no degradable, capas/activos ausentes,
  ruta Wizard→adaptador→Video3D sin modelos.
- [ ] Pruebas locales, commit, PR contra development, Cursor, CI y merge normal.

## PR B — Catálogo de escenas candidatas, no aprobado

- [x] Contrato separado de plantilla: ID/versión, familia, estado de revisión,
  slots y tipos admitidos, parámetros acotados, duración, coste y límites.
- [x] Compilar a escenas ordinarias editables, sin nuevos motores de render.
- [x] Preparar 24 candidatos diferenciados: cine narrativo, videoclip y espacio.
- [x] Cubrir naves, persecución, intercambio de disparos, impacto y explosión
  estilizada mediante assets/efectos programáticos; no prometer física realista.
- [x] Assets de demostración originales y reemplazables; probar dos bindings
  diferentes para verificar que una plantilla no está fijada a un personaje.
- [x] Validación de slots, referencias, límites, determinismo y escenas sin vídeo IA.
- [ ] Pruebas locales, commit, PR, Cursor, CI y merge del mecanismo experimental,
  manteniendo los candidatos fuera de las recomendaciones aprobadas por defecto.

## PR C — Galería visual y «Abrir en editor»

- [x] Galería con ficha, preview real, finalidad, slots, límites y ejemplos de pedido.
- [x] Abrir cada escena de muestra en el editor real con su configuración intacta.
- [x] Recuperar escenas desde sus resultados/metadata cuando exista un snapshot;
  si falta, informar, no reconstruir una escena inventada a partir del MP4.
- [x] Elegir pendiente / conservar / descartar; exportar decisiones con versión
  de catálogo para que un agente no confunda selección local con aprobación global.
- [x] E2E sin proveedores: abrir, editar, guardar/reabrir y navegar a escena correcta.
- [x] Render local en serie, resolución moderada y CPU/software cuando sea posible;
  registrar fallos reales y no reemplazar clips fallidos con placeholders aprobados.
- [x] Publicar una URL local/LAN de revisión y entregar inventario verificable.
- [ ] Pruebas locales, commit, PR, Cursor, CI y merge según dependencias.

## Dependencias y parada honesta

`A` fija la autoridad de generación. `B` puede prepararse de forma aislada sin
pisar el Wizard; su conexión depende de `A`. `C` depende del contrato de `B`.
No apilar PRs que toquen los mismos puntos de integración: mezclar y rebasar la
siguiente rama desde development. Luna puede encargarse de assets geométricos,
tests y UI acotada; el principal supervisa la autoridad, contratos e integración.

La selección definitiva de las plantillas necesita el feedback del usuario.
No se continúa automáticamente borrando el catálogo previo ni alterando el
planificador de Director. Esta entrega tampoco completa las fases 02b–13 del
plan arquitectónico general de producción.

## Evidencia requerida

Para cada PR: SHA, pruebas locales, CI actual, resultado de Cursor y merge.
Para cada preview: plantilla/versión, bindings, parámetros, política, SHA del
compositor, duración, resolución, estado de render y ruta a escena editable.
Una galería visible no demuestra recuperación tras reinicio ni generación IA.

## Encargo ampliado posterior a la galería (2026-09-06)

El usuario solicita terminar este piloto y después redactar y ejecutar un plan
detallado por fases/PRs: gran mejora de composición 2D/2.5D primero, escenario
3D compartido después, biblioteca amplia de acabados y personajes consistentes
con varias vistas/movimiento al final. Objetivo de hasta 50 propuestas
genuinamente distintas por bloque; no inflar el número con variaciones de zoom
o color. Separar encuadre, ángulo, trayectoria, óptica y montaje. No vender
«sin VRAM»: el render puede usar GPU aunque no use inferencia de vídeo.

Esta ampliación está **diseñada en [PROCEDURAL_VIDEO_ROADMAP.md](PROCEDURAL_VIDEO_ROADMAP.md),
pendiente de implementación P01 en adelante**. Incluye inventarios de 50 propuestas
2D/2,5D, 50 3D y 50 técnicas de acabado, no funcionalidades ya entregadas.
No se mezcla ahora un motor nuevo ni se declara que estas 24 candidatas la
resuelvan. La propuesta recomendada es un editor con dos tipos de escena y
contratos compartidos; no dos editores ni herramientas de modelado tipo Blender.

## Historial de revisión y evidencia local

PR #168, HEAD `3aaa65cb5b3e5c74e62f99a3856a81279bf12a41`: 120 tests locales
en checkout de ese HEAD y build pasan; CI required verde. Se corrigieron dos
hallazgos iniciales de Cursor, pero su nueva revisión no ha podido ejecutarse por límite
de uso/gasto. Posteriormente IAnMove mezcló #168 (`8542bf74`) y autorizó expresamente
seguir sin Cursor temporalmente. No se cambian protecciones: revisión independiente
con otro agente y CI siguen siendo condiciones del merge normal.

Piloto local inicial: 27 tests de catálogo/compilación/arte/decisiones y 3 E2E.
La revisión final de C1/#173 amplió la batería a 36 tests enfocados y 5 E2E
ejecutados en `ui/e2e/specs`. Galería con 24 MP4 reales, reproducción/seek y
guardado del snapshot probado contra servidor aislado. Son 4 s, 1280×720/30,
sin audio; ningún proveedor de vídeo IA se ha usado. La herramienta reproducible
también exportó una composición y una escena GLB con la UI construida: 2/2.

La herramienta sirve build estático en carpeta temporal con API cerrada, Host/
Origin validados e índice de archivos. No usa el servidor de desarrollo ni proxy
al backend. Las pruebas de contrato HTTP usan una cabecera MP4 mínima: eso prueba
el transporte/metadata, no un MP4 válido. Los renders reales se verifican con ffprobe.

Los 24 originales coral fueron aprobados visualmente y publicados como
[referencias de estilo/acción](https://github.com/IAnMove/hocuspocus/releases/tag/procedural-style-reference-v1),
no release de aplicación. No reescribir sus sidecars ni atribuirles cambios futuros.
B (#169), C1 (#173) y C2 (#175, `38a90aa6`) ya están mezclados. Continuar desde
development actualizado, sin volver a aplicar sus commits.
Ver P00D del roadmap para selector con vídeos de referencia y assets de Library
reemplazables. La prueba pintada adicional no sustituye estos originales.

Para mantener revisables los cambios, C se divide en **C1 galería/editor** y
**C2 herramienta reproducible**. No se mezclan ~1.800 líneas de UI, pruebas y
servidor de QA en un único PR.
