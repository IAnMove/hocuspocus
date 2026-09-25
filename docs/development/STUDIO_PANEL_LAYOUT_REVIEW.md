# Revisión pendiente de la distribución de paneles de Studio

Fecha: 7 de septiembre de 2026. Origen: prueba manual del flujo Viggle.
Estado: **dirección concretada el 11/09/2026** — Wizard lateral plegable; Generación directa y Director en el área principal. Implementación en `feat/unified-main-workspace-20260911`.

## Destinos (antes → después)

| Destino | Antes | Después |
|---|---|---|
| Ask to the Wizard | Columna izquierda plegable | Igual; al plegarlo el área principal ocupa el ancho |
| Generación directa | Columna fija 420px + galería | Formulario en el área principal; resultados al lado en XL |
| Biblioteca (imágenes/vídeos/…) | `mediaFilter` compartido con el generador | Destino `section`: solo galería; el prompt se conserva |
| Director | Columna 420px; oculto en Estudios hasta #323/#326 | Área principal; abrir Director siempre lo muestra |
| Comic Director | Cómics + sidebar Director | Director en el área principal (incluye panel de cómic) |
| Story Lab, Series, 2.5D, 3D, Animate, personajes, Replace | Área principal | Igual, sin columna de generación |
| Ajustes / Productions | Overlay | Overlay |
| Móvil | Overlay de generación; Wizard aparte | Una columna; Wizard bajo demanda |

`visibleWorkspaceSurface()` separa generate / director / section. `sidebarOpen` + `sidebarMode` siguen siendo el contrato de apertura; ya no montan una columna permanente.
El usuario pidió documentar el problema para revisar la distribución después de
las pruebas de Viggle. El encargo de unificación del 11/09/2026 concreta esa
revisión: no ampliar la columna de 420px, sino trasladar el trabajo al área
principal.

Actualización de la misma sesión: al probar la guía, el usuario concretó un cambio
acotado para Viggle: una sección destacada **Reemplazar personaje**, junto a Vídeo
2,5D y Vídeo 3D, con preparación del fotograma y generación dentro de un espacio
amplio. Ese flujo se implementa en la adopción WanGP; no resuelve ni sustituye la
revisión general de paneles que recoge esta nota.

## Problema observado

La segunda columna, que contiene los controles de la herramienta activa, acumula
guía, referencias, opciones, prompt y acciones. En el paso de edición de imagen
de Viggle resulta difícil acceder a todo el contenido. La captura del usuario
muestra mucho espacio horizontal disponible en la zona de medios de la derecha,
mientras la columna de herramientas sigue estrecha y obliga a desplazarse por
varias zonas. Una pantalla especialmente ancha no resuelve la falta de espacio
útil dentro de esa columna; en otras pantallas puede ser todavía más limitante.

El problema se detecta con Viggle, pero afecta a cómo se distribuye el espacio de
trabajo. No se considera resuelto por añadir una guía o reducir su texto.

## Intención del usuario

- Poder hacer grande la segunda columna o panel de herramientas y que se adapte
  a la pantalla y al trabajo que se está haciendo.
- Valorar plegar la zona de medios hacia la derecha para ceder ese espacio a los
  controles cuando se necesita concentrarse en ellos.
- Mantener abiertas las decisiones sobre la organización general: la zona
  izquierda no funciona exclusivamente como acceso rápido y la zona derecha no
  contiene solo medios. El editor de vídeo, por ejemplo, tiene necesidades
  propias de espacio e interacción.
- Evitar que una mejora provisional obligue a mover ahora el menú o desencadene
  un rediseño general de navegación. Las decisiones generales se revisarán después
  de probar Viggle con tranquilidad.

## Opciones para comparar, todavía sin elegir

| Opción | Qué permitiría | Qué debe comprobarse antes de decidir |
| --- | --- | --- |
| Ampliar o redimensionar herramientas | Dar más ancho a controles y referencias | Ancho mínimo de los otros paneles, altura útil, teclado y recuperación del tamaño inicial |
| Plegar medios hacia la derecha | Dedicar temporalmente gran parte del espacio a herramientas | Cómo recuperar medios y conservar visible la navegación sin moverla por obligación |
| Vista de trabajo centrada en herramientas | Adaptar el espacio al paso activo y al tamaño de pantalla | Evitar saltos inesperados, conservar la orientación y distinguir las necesidades del editor de vídeo |

Estas son alternativas para una conversación y un prototipo posterior, no una
selección de diseño ni una lista autorizada de cambios de código.

## Criterios para esa revisión

1. Se puede completar Viggle: cargar vídeo, editar el fotograma, escribir el
   prompt, generar, aplicar y volver. Ningún control esencial queda inaccesible.
2. El espacio liberado se aprovecha realmente: no basta con ocultar medios y
   conservar el mismo ancho fijo de herramientas.
3. Navegación, acción principal y retorno a la vista normal son localizables.
   Reducir los desplazamientos anidados y revisar cuánto ocupa la información
   de sistema frente a los controles del trabajo activo.
4. Plegar, ampliar o restaurar no pierde referencias, prompt, selección, estado
   del editor ni tareas que ya se estén ejecutando.
5. Comparar pantalla ancha, portátil de altura reducida, tablet y móvil; revisar
   zoom del navegador, teclado y textos en español e inglés. Las resoluciones
   concretas se fijarán al preparar el prototipo.
6. Revisar imagen, vídeo, herramientas y editor de vídeo por separado antes de
   imponer una distribución única.

## Cómo retomarlo

Revisar primero el estado vigente de los paneles y los PR abiertos para evitar
duplicados. Reproducir el problema con el flujo real de Viggle, comparar bocetos
de las opciones y acordar con el usuario un cambio acotado. Solo entonces definir
el contrato de navegación, el alcance de implementación y sus pruebas.

Contexto funcional: [adopción WanGP y flujo Viggle](WANGP_1272_ADOPTION.md).
