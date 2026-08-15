# Análisis estratégico de Loreframe Lab

Fecha de referencia: 15 de agosto de 2026  
Estado: documento de dirección conceptual, no especificación cerrada  
Alcance: producto, experiencia, arquitectura conceptual, oportunidades, riesgos,
métricas y posible secuencia de ejecución.

## Resumen ejecutivo

Loreframe no debería intentar ganar como otra suite que agrupa muchos
generadores de imagen, vídeo, audio y 3D. Esa capa se está convirtiendo
rápidamente en una funcionalidad intercambiable y muy competida.

La oportunidad más grande y defendible es convertir Loreframe en:

> El sistema operativo local-first para producir mundos narrativos
> persistentes: conserva el canon, lo transforma en producciones ejecutables,
> coordina diferentes modelos, permite revisar cada plano y aprende de las
> decisiones del creador.

Una posible formulación de producto:

> Crea el mundo una vez. Produce episodios coherentes, plano a plano.

El problema importante no es generar un clip atractivo de manera aislada. Es
generar el plano 30 sin perder el protagonista, el mundo, el diálogo, el orden
ni las decisiones aprobadas en los 29 anteriores; poder sustituir ese plano sin
rehacer el resto; cerrar la aplicación; y continuar al día siguiente con todo
el historial recuperable.

La recomendación principal es concentrar el producto durante una etapa:

1. Series Lab como producto insignia.
2. Una Production Board universal como experiencia de revisión.
3. Un Continuity Compiler como capa de inteligencia.
4. Un grafo común —LoreGraph como nombre conceptual— como plataforma futura.

## La oportunidad de categoría

La propuesta no sería “generación audiovisual con IA”, sino “producción
narrativa persistente con IA”.

La distinción es importante:

- Un generador convierte un prompt en un archivo.
- Una herramienta de producción convierte una intención en un plan revisable.
- Un sistema operativo de producción conserva la relación entre canon,
  decisiones, referencias, planos, intentos, assets, montaje y versiones.

Loreframe ya contiene varias piezas del tercer nivel. Todavía están repartidas
entre Story Lab, Series Lab, Director, Comic, Productions, Activity, el editor y
la galería general. Unificarlas es más valioso que seguir añadiendo modalidades.

## Por qué no basta con integrar más modelos

El espacio genérico de creación audiovisual está cada vez más cubierto:

- Adobe Firefly reúne generación de imagen, vídeo y audio, Boards, editor,
  workflows visuales y modelos asociados.
- LTX Studio combina elementos persistentes, storyboard, timeline y generación.
- Runway ofrece workflows reutilizables que encadenan operaciones creativas.
- ComfyUI ya ocupa una posición muy fuerte como grafo de ejecución de bajo nivel.

La inferencia estratégica es que competir mediante más modelos, controles, tabs
o nodos será una carrera con poca defensa: cada integración se puede copiar y
cada generación de modelos obliga a rehacer parte del producto.

Loreframe debería tratar los modelos como renderers intercambiables. El activo
duradero sería:

- El mundo estructurado.
- Las decisiones editoriales.
- La memoria de lo aprobado y rechazado.
- Los manifests exactos de referencias y capacidades.
- La recuperación de trabajos.
- La continuidad entre escenas y episodios.
- La posibilidad de recompilar una producción para otro modelo.

## Cimientos que ya existen

La tesis no parte de cero:

- Story Lab conserva una biblia editable y puede derivar producciones de tipo
  cómic, película, videoclip y tráiler desde una fuente narrativa común.
- Series Lab modela la jerarquía Serie → Temporada → Episodio → Escena → Plano
  → Intentos, con IDs estables.
- Los episodios congelan un snapshot del canon y no deberían cambiar
  silenciosamente al modificarse el mundo principal.
- Los intentos de render son append-only y conservan prompt, modelo,
  configuración, referencias, tiempos y resultados anteriores.
- Los manifests de referencias explican qué se seleccionó, qué se omitió y por
  qué.
- Comic → vídeo ya utiliza una fase PRE versionada, fingerprint, pruebas,
  validación y aprobación antes de gastar en la producción completa.
- El registro de tareas y los pipelines recuperables empiezan a convertir las
  generaciones en trabajos duraderos.
- La biblioteca de estilos ya incorpora fuente, autor y licencia como parte de
  su identidad.

Referencias internas:

- [Arquitectura de Series Lab](series-lab/PHASE0_ARCHITECTURE.md)
- [Implementación de Series Lab](series-lab/IMPLEMENTATION.md)
- [Adaptación Comic → vídeo](COMIC_VIDEO_ADAPTATION.md)
- [Story → Comics → Vídeo](MAESTRO_X_STORY_COMICS_VIDEO.md)
- [Auditoría técnica y de UI](AUDITORIA_CODIGO_UI_2026-08-13.md)

## Una historia como código fuente

Una analogía útil para guiar el producto:

| Loreframe | Desarrollo de software |
| --- | --- |
| Biblia y canon | Código fuente |
| Revisión del canon | Commit |
| Plan de escenas y planos | Representación intermedia |
| Prompt efectivo y referencias | Compilación para un renderer |
| Intento generado | Build |
| Controles automáticos | Tests |
| Clip aprobado | Artefacto aceptado |
| Montaje final | Release |

Los modelos pueden cambiar sin que se pierda el proyecto. Un plano aprobado
debería poder recompilarse para MiniMax, LTX, Wan u otro proveedor manteniendo
su intención, referencias, posición e historial.

## Arquitectura conceptual del producto

El núcleo común debería aproximarse a:

    Mundo / canon
        ↓
    Producción
        ↓
    Episodio o secuencia
        ↓
    Escena
        ↓
    Plano
        ↓
    Intentos de generación
        ↓
    Asset aprobado
        ↓
    Montaje versionado

Alrededor del grafo:

- Personajes, relaciones, localizaciones, props, voces y estilos.
- Referencias, fuentes, licencias, consentimientos y hashes.
- Adaptadores de modelos y snapshots de capacidades.
- Trabajos, checkpoints, cancelación y recuperación.
- Evaluaciones automáticas y revisión humana.
- Exportadores y procedencia del master final.

Story, Series, Comic, Trailer, Director y Studio deberían evolucionar hacia
vistas o adaptadores sobre esta estructura, no mantener fuentes de verdad
independientes.

## Mejoras conceptuales de la experiencia

### 1. Navegación centrada en proyectos

El creador normalmente piensa:

    Proyecto → Mundo → Producción → Plan → Generación → Revisión → Montaje

No piensa primero en:

    Imagen → Vídeo → Audio → Director → Editor → Outputs

La pantalla principal debería abrir proyectos y entregables recientes. Los
tipos de media y modelos pasarían a ser acciones dentro del proyecto. Studio
seguiría disponible como modo experto y laboratorio manual.

### 2. Production Board universal

El patrón de Series Review debería ser la experiencia común:

- Columna de planos o slots en orden.
- Reproductor central.
- Inspector de intención, datos e intento activo.
- Historial inmutable por slot.
- Regeneración en la misma posición.
- Comparación A/B entre intentos.
- Play all y resaltado del plano actual.
- Aprobación individual y masiva.
- Trim no destructivo.
- Montaje y exportación como resultado versionado.

Outputs seguiría existiendo, pero como biblioteca transversal. La vista primaria
de cada asset debería responder inmediatamente:

- A qué proyecto pertenece.
- Qué plano y qué intento lo produjeron.
- Qué referencias, modelo y prompt se utilizaron.
- Si está aprobado, descartado, obsoleto o pendiente de revisión.

### 3. ADN creativo opcional

Cada proyecto debería poder definir un contrato creativo reutilizable:

- Protagonistas y referencias primarias.
- Invariantes de rostro, cuerpo, vestuario y voz.
- Mundo, localizaciones, props y reglas.
- Estilo visual, cámara y paleta.
- Idioma hablado y variante regional.
- Pronunciaciones protegidas.
- Política de audio, música y ambiente.
- Derechos y procedencia.

Debe continuar siendo opcional. Un videoclip abstracto puede no necesitar
consistencia de protagonista; una serie episódica sí.

### 4. Separar intención de ejecución

Por defecto, el usuario debería editar intención creativa. Loreframe compilaría
el prompt efectivo según el modelo:

- Capacidad de first/last frame.
- Límite y semántica de referencias.
- Formato de diálogo.
- Duración válida.
- Audio nativo o condicionado.
- Resolución y frame grid.
- Restricciones conocidas del renderer.

El prompt compilado seguiría visible y editable en modo avanzado, pero la
calidad del producto no debería depender de que el usuario conozca contratos
internos de cada modelo.

### 5. Análisis de impacto

Cuando se modifica una entidad, Loreframe debería mostrar qué queda obsoleto:

- Cambiar una frase recalcula duración y marca audio/vídeo dependiente.
- Cambiar la apariencia de un personaje identifica los planos afectados.
- Cambiar una localización no invalida clips que no la utilizan.
- Cambiar un trim modifica el montaje, pero no el archivo original.
- Cambiar de modelo recompila el plano sin perder su posición ni sus intentos.

Esto sería una forma visual y comprensible de control de dependencias.

## Apuestas principales

### Apuesta 1: Production Board

Hipótesis:

> Toda generación importante debería pertenecer a una producción persistente
> con slots estables.

MVP:

- Un único flujo inicial: episodio corto o videoclip.
- Importar un plan de Director.
- Slots ordenados con intentos y aprobación.
- Regeneración en posición.
- Play all, trim y montaje.
- Persistencia y recuperación tras recargar o reiniciar.

No incluir todavía colaboración compleja, timeline multicapa ni edición
profesional frame-perfect.

### Apuesta 2: Continuity Compiler

Hipótesis:

> El mayor ahorro económico y emocional vendrá de evitar generaciones
> incorrectas por identidad, audio, idioma, referencias o prompting.

Primer alcance:

- MiniMax como renderer inicial bien entendido.
- Idioma y variante regional explícitos.
- Duración calculada a partir de sílabas, pausas y actuación.
- Omisión real de instrucciones de audio cuando no corresponden.
- Protagonista de referencia opcional.
- Hoja de estilo conectada con el proyecto.
- Enrutamiento según capacidades.
- Linter de sobrecarga, repetición y contradicciones del prompt.
- Vista de intención y vista de prompt compilado.

### Apuesta 3: Quality OS

Loreframe no necesita resolver visión artificial general. Puede reunir checks
pequeños y explicables:

- ASR para validar idioma y contenido hablado.
- Detección de habla o canto no solicitados.
- Comparación de duración de diálogo y clip.
- Similitud de protagonista y vestuario.
- Presencia de localización y props esperados.
- Adherencia aproximada a first/last frame.
- Vídeo vacío, congelado o corrupto.
- Audio vacío, corrupto o con actividad inesperada.
- Duración, resolución, canales y codec.
- Repetición de composición o movimiento entre planos.

La salida ideal:

    28 planos listos para revisar
    3 planos dudosos
    1 plano falló el diálogo

El sistema filtra excepciones. El humano conserva la decisión artística.

### Apuesta 4: Production Memory

Cada intento puede alimentar memoria privada del proyecto:

- Qué estrategia de referencia conserva mejor a cada personaje.
- Qué modelo funciona mejor según el tipo de plano.
- Qué duración evita audio alucinado.
- Qué estructuras de prompt provocan rechazos.
- Qué configuraciones acepta normalmente ese creador.
- Qué recetas consumen menos tiempo o créditos por segundo aprobado.

El ciclo sería:

    Plan → Render → Evaluación → Decisión → Aprendizaje → Siguiente plan

Por defecto este aprendizaje debería permanecer local. Cualquier contribución
colectiva tendría que ser voluntaria, granular y separada entre métricas,
metadatos y media.

La prueba estratégica:

> El episodio 10 debería necesitar menos regeneraciones que el episodio 1.

### Apuesta 5: LoreGraph y .lorepack

LoreGraph es un nombre conceptual para el grafo común. .lorepack sería un
formato portátil y versionado para:

- Canon y revisiones.
- Personajes, relaciones, localizaciones, props y voces.
- Escenas, planos y timeline.
- Referencias, hashes y procedencia.
- Prompt efectivo, modelo, versión, seed y capacidades.
- Intentos, aprobaciones, rechazos y razones.
- Evals automáticos.
- Linaje hasta el montaje.
- Derechos, atribuciones y consentimientos.

Una forma razonable sería un paquete ZIP con manifest JSON, JSON Schema,
versionado semántico, migraciones y assets opcionales dirigidos por hash.

La especificación podría ser abierta. El valor no debería depender de bloquear
los archivos, sino de tener el mejor runtime, compilador, memoria y ecosistema.

## Público inicial

### Persona principal

Creadores independientes y pequeños estudios que publican contenido narrativo
recurrente:

- Series animadas o webseries.
- Ficción corta para YouTube.
- Cómic transformado en vídeo.
- Bandas o avatares virtuales.
- Videoclips con universo visual persistente.
- Microestudios que mantienen personajes, marca y estilo.

Trabajo principal:

> Tengo una canción, guion o premisa. Conviértela en un montaje que pueda
> evaluar, mantén su identidad entre planos y permíteme corregir sólo lo que
> falla.

### Persona secundaria

Agencias y equipos de previsualización que necesiten:

- Proponer varias piezas.
- Mantener identidad de campaña.
- Revisar antes de gastar.
- Exportar un rough cut a su editor profesional.

### Persona facilitadora

Operadores técnicos que controlan modelos locales, VRAM, colas, tiempos y
recuperación sin bloquear al creador.

### Fuera del foco inicial

- Usuario casual que espera generación instantánea.
- Editor profesional que necesita sustituir Premiere o Resolve.
- Especialista 3D que necesita sustituir Blender.
- Empresa grande antes de disponer de seguridad, colaboración y licencia.

## El killer demo

La demostración más convincente no sería un clip aislado espectacular:

1. Crear dos personajes y un mundo originales.
2. Aprobar ADN visual, voces, idioma y canon.
3. Introducir la premisa de un episodio.
4. Obtener beats, escenas y planos editables.
5. Revisar duración, coste y recursos antes de renderizar.
6. Generar frames y clips mediante una cola duradera.
7. Cerrar Loreframe durante la ejecución.
8. Volver y encontrar una bandeja de excepciones.
9. Corregir un plano y regenerarlo en su posición.
10. Reproducir todos los clips en orden.
11. Recortar sin modificar originales.
12. Montar y exportar.
13. Crear el episodio siguiente heredando únicamente el canon aprobado.

La prueba de producto debería ser una pequeña temporada de cinco episodios de
60–120 segundos, no un único vídeo.

## Un mundo, muchas publicaciones

Después de dominar el flujo episódico, una misma IP podría producir:

- Episodios.
- Cómics.
- Tráilers.
- Videoclips.
- Recaps y teasers.
- Piezas sociales.
- Material promocional.
- Assets para juegos o reconstrucción 3D.

La promesa no sería “crear todo con un clic”, sino:

> No reconstruyas tu mundo desde cero para cada formato.

## Interoperabilidad profesional

Loreframe debería proporcionar un montaje sólido para revisar, recortar,
comparar y aprobar. No debería competir con un NLE completo.

OpenTimelineIO puede utilizarse como base de intercambio editorial. Representa
clips, tiempos, tracks, transiciones, markers y metadatos, y dispone de
adaptadores para formatos como FCP XML, AAF o EDL.

Posibles exportaciones:

- Master de vídeo.
- Clips aprobados con nombres estables.
- OpenTimelineIO.
- FCP XML o EDL cuando el adaptador sea suficientemente fiable.
- Stems de audio y diálogos.
- Subtítulos.
- Manifest de producción.
- Paquete de referencias.

También podría incorporarse C2PA/Content Credentials para adjuntar procedencia
verificable a imágenes, audio y vídeo exportados.

## Plataforma y ecosistema

Después de estabilizar LoreGraph, podría definirse un SDK con plugins tipados:

- Writer.
- Planner.
- Image renderer.
- Video renderer.
- Audio renderer.
- Evaluator.
- Assembler.
- Exporter o publisher.

Cada plugin debería declarar:

- Identidad, versión y compatibilidad de schema.
- Capacidades y límites.
- Entradas y salidas tipadas.
- Recursos de CPU, GPU, VRAM, disco y red.
- Permisos y secretos requeridos.
- Licencia, autor, hashes y firma.
- Progreso, cancelación y recuperación.

Los plugins deberían ejecutarse aislados del proceso principal. Para un futuro
marketplace no sería seguro instalar código y dependencias arbitrarios en el
entorno principal.

Las recetas de producción serían más valiosas que prompts sueltos. Una receta
podría describir:

    Canon → adaptación → plan → referencias → render
          → evaluación → review gate → retake → montaje

El marketplace sólo tendría sentido después de demostrar reproducibilidad,
procedencia, aislamiento y compatibilidad.

## Flywheel defendible

    Más proyectos originales
        ↓
    Más intentos con manifests exactos
        ↓
    Más decisiones y razones de rechazo
        ↓
    Mejores evaluaciones, routing y recetas
        ↓
    Menos regeneraciones y mayor continuidad
        ↓
    Más creadores y producciones

Los modelos son sustituibles. El grafo, las decisiones, los benchmarks y la
memoria de producción permanecen.

## Métricas

### Métrica norte

> Minutos finales aprobados por hora de trabajo humano.

Debe acompañarse de coste o minutos GPU por minuto aprobado para evitar mejorar
velocidad a costa de desperdicio.

### Activación y finalización

- Porcentaje de proyectos que alcanzan un rough cut reproducible.
- Tiempo desde brief hasta primer montaje.
- Exportaciones por proyecto iniciado.
- Porcentaje de usuarios que reabre el proyecto en una segunda sesión.

### Calidad

- Porcentaje de planos aprobados al primer intento.
- Intentos medios por plano aprobado.
- Incidencias de continuidad por minuto.
- Errores de idioma o diálogo.
- Regeneraciones causadas por identidad, audio, estilo o prompt.

### Fiabilidad

- Trabajos recuperados correctamente después de cierre o reinicio.
- Producciones completadas sin perder estado.
- Porcentaje de lotes nocturnos que llegan a estado revisable.
- Tiempo medio hasta detectar y aislar un fallo.

### Retención

- Creadores que inician un segundo episodio en 14 días.
- Episodios terminados por creador activo al mes.
- Reutilización de personajes, mundos y estilos aprobados.
- Mejora de intentos por aprobación entre episodios sucesivos.

## Riesgos

### 1. Licencia comercial

Es el bloqueo empresarial principal. La licencia actual permite uso y
modificación no comercial, pero prohíbe vender u ofrecer el derivado como
producto de pago, servicio alojado o API sin licencia separada.

Antes de monetizar habría que:

1. Negociar una licencia comercial con el propietario de WanGP; o
2. Diseñar, con asesoramiento jurídico, un núcleo realmente independiente para
   LoreGraph, coordinación, evaluaciones y colaboración, dejando runtimes
   externos como adaptadores.

Mover archivos o carpetas no constituye una separación jurídica o técnica.

Referencias:

- [Licencia resumida del repositorio](../LICENSE)
- [Licencia autoritativa](../app/LICENSE.txt)

### 2. Fiabilidad y deuda técnica

Una herramienta de producción no puede mezclar IDs, sobrescribir intentos,
perder trabajos o crecer indefinidamente por polling. Antes de escalar deben
resolverse los problemas de datos, seguridad, tareas, planner y CI de la
auditoría técnica.

### 3. Scope sprawl

Imagen, vídeo, audio, cómic, 3D, edición, LoRAs y series pueden convertirse en
una colección de productos. Cada nueva función debería responder:

> ¿Mejora la creación, continuidad, revisión o finalización de una producción?

### 4. Copyright, marcas y consentimiento

Las demostraciones principales deberían utilizar IP original o claramente
licenciada. Universos conocidos pueden servir como pruebas privadas, pero no
deberían definir el marketing.

Fuente, derechos, atribución y consentimiento de rostro o voz deberían ser
metadatos de primera clase.

### 5. Hardware y distribución

El producto actual requiere NVIDIA, grandes descargas y mucho almacenamiento.
Esto limita inicialmente el mercado a prosumidores y estudios pequeños.

Una arquitectura híbrida puede explorarse después, pero no antes de resolver
licencia, privacidad, seguridad y fiabilidad.

### 6. Privacidad frente a aprendizaje colectivo

Local-first es una ventaja, pero limita un dataset colectivo. La solución debe
ser opt-in:

- Aprendizaje personal local por defecto.
- Telemetría colectiva desactivada por defecto.
- Aportación separada de métricas, metadatos y media.
- Exportación y borrado verificables.

## Modelo de negocio, condicionado a la licencia

Una estructura posible después de resolver los derechos:

- Spec y formato abiertos para favorecer adopción.
- Runtime local básico gratuito.
- Pro individual: memoria avanzada, backups, sync y evaluaciones.
- Team/Studio: roles, comentarios, approvals y runners compartidos.
- Enterprise/on-prem: SSO, políticas de modelos, auditoría y soporte.
- Marketplace posterior: comisión sobre adaptadores, recetas y eval packs
  verificados.

No se recomienda comenzar revendiendo GPU o créditos. Es intensivo en capital y
no crea la diferenciación principal.

## Qué no construir todavía

- Más tabs sin unificarlas con una producción.
- Un competidor completo de Premiere, Resolve, Blender o una DAW.
- Otro editor de nodos que clone ComfyUI.
- Un marketplace antes de un schema y SDK estables.
- Publicación social automática.
- Colaboración CRDT compleja sin un caso real.
- Una promesa de episodio largo completamente autónomo.
- Aprobación artística automática.
- Un modelo fundacional propio.
- Una estrategia comercial antes de resolver la licencia.

## Secuencia recomendada

### Etapa 0 — Derecho a confiar

- Resolver los defectos P1 de la auditoría.
- Estabilizar datos, IDs, tareas, recuperación y CI.
- Definir la estrategia de licencia.
- Congelar el público inicial y el flujo de referencia.

### Etapa 1 — Flujo de oro

- Un episodio original de 60–120 segundos.
- Dos protagonistas.
- Ocho a doce planos.
- Canon, plan, referencias, renders, revisión y montaje.
- Recuperación completa después de reiniciar.
- Production Board universal.

### Etapa 2 — Ventaja de calidad

- Continuity Compiler.
- ADN creativo.
- Evals locales.
- Razones estructuradas de rechazo.
- Bandeja de excepciones.
- Comparación de coste y aceptación entre modelos.

### Etapa 3 — Memoria y portabilidad

- Production Memory.
- LoreGraph v0.1.
- Importación y exportación .lorepack.
- OpenTimelineIO.
- Procedencia y Content Credentials.

### Etapa 4 — Plataforma

- SDK de adapters.
- Plugins aislados.
- Sync y review de equipo.
- Benchmark opt-in.
- Registry firmado.
- Marketplace piloto.

## Experimentos de validación

Antes de construir la plataforma completa:

### Experimento A — Finalización

Comparar el flujo actual con Production Board.

Éxito sugerido:

- Incrementar al menos un 25 % la conversión de proyecto iniciado a vídeo
  exportado.

### Experimento B — Compilador

Registrar el motivo de cada regeneración y activar ADN creativo, duración y
contratos MiniMax.

Éxito sugerido:

- Reducir al menos un 30 % las regeneraciones atribuidas a audio, idioma,
  identidad o formato de prompt.

### Experimento C — Producción nocturna

Generar un episodio completo con revisión posterior por excepciones.

Éxito sugerido:

- Al menos el 70 % de los planos llega a un estado revisable sin intervención
  durante la ejecución.

### Experimento D — Aprendizaje episódico

Producir cinco episodios con el mismo mundo y personajes.

Éxito:

- Menos intentos por plano aprobado en episodios posteriores.
- Menos incidencias de continuidad.
- Menor tiempo humano por minuto final.

## Decisión estratégica recomendada

Si sólo pudiera financiarse una apuesta:

> LoreGraph abierto + evaluaciones de continuidad + SDK model-agnostic para
> producción episódica local-first.

En el producto inmediato:

> Series Lab como insignia, Production Board como experiencia universal y
> Continuity Compiler como inteligencia.

Loreframe no necesita ser más ancho durante una etapa. Necesita demostrar que
una persona puede crear, detener, reabrir, corregir y terminar cinco episodios
consecutivos con identidad estable, y que cada episodio requiere menos trabajo
que el anterior.

Si lo consigue, dejará de ser una colección potente de herramientas y empezará
a constituir una categoría propia.

## Fuentes externas consultadas

Estas fuentes reflejan el contexto competitivo y de interoperabilidad en la
fecha indicada; conviene revisarlas periódicamente:

- [Adobe Firefly Workspace](https://helpx.adobe.com/sg/firefly/web/get-started/access-the-app/firefly-workspace-overview.html)
- [LTX Studio](https://website.ltx.studio/)
- [Runway Workflows](https://help.runwayml.com/hc/en-us/articles/45763528999699-Introduction-to-Workflows)
- [ComfyUI Workflows](https://docs.comfy.org/basic-concepts/workflow)
- [OpenTimelineIO](https://opentimelineio.readthedocs.io/en/latest/index.html)
- [Adaptadores de OpenTimelineIO](https://opentimelineio.readthedocs.io/en/latest/tutorials/adapters.html)
- [Content Authenticity Initiative y C2PA SDK](https://opensource.contentauthenticity.org/)

