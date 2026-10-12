# Guía de uso de HocusPocus

Qué es cada pestaña y a dónde ir después. HocusPocus es un estudio local: todo lo
que generas se guarda en la **carpeta de salida** elegida en la barra lateral.
Los **Workspaces** son colecciones de referencias y notas, no carpetas.

## Barra superior

- **Crear → Generación directa (Studio):** un recurso por trabajo. Modos
  **Imagen**, **Vídeo**, **Audio** (voz, música, efectos, mezcla), **3D**,
  **Editar** (retake, outpaint, repaint, recast, edit anything) y
  **Herramientas** (upscale, revoice, quitar fondo).
- **Crear → Estudios:** los laboratorios de la tabla siguiente.
- **Producción:** Director, Producciones, Producciones musicales, Obras y Video Editor.
- **Media / Biblioteca:** filtros Todo, Imágenes, Vídeos, Videoclips, Tráilers,
  Capítulos, Audio, 3D, Escenas y Documentos; además **Proyectos** (documentos
  que puedes reabrir), **Recursos** (archivos fuente y resultados reutilizables),
  **Workspaces**, Edits, Multi-clip y Favoritos.
- **Actividad:** cola de tareas, uso de GPU y RAM, errores; cancelar, reintentar
  o reanudar una tarea.
- **Ajustes:** idioma, tema, modelos locales, proveedores remotos, integraciones
  (token MCP) y almacenamiento.
- **Ayuda:** el tutorial dentro de la app, con capturas de la interfaz actual.
- **Ask the Wizard:** director conversacional. Describe lo que quieres; abre el
  laboratorio adecuado, rellena formularios o lanza trabajos y deja un recibo.

## Estudios

| Pestaña | Para qué sirve |
| --- | --- |
| **Story Lab** | Historia, personajes, lugares y canción de un proyecto; desde la canción se pasa al videoclip. |
| **Series Lab** | Serie animada completa: biblia, personajes con voz, capítulos por guion, render en el servidor, versiones de idioma y montaje. |
| **Cómics** (Comic Studio) | Páginas y viñetas con sus imágenes; un cómic terminado puede convertirse en película o tráiler. |
| **Character Creator** | Kits de personaje reutilizables: referencias, rig plano de recortable, bocas (26 estilos), voz y cara 3D. |
| **Lips Creator** | Dibuja bocas y las vincula a sonidos para el lip-sync 2D y 3D. |
| **Vídeo 2,5D** (Scene Animator) | Escenas de capas e imágenes: cámara, movimientos, rótulos, letra, efectos y exportación MP4. |
| **Vídeo 3D** | Monta GLB, kits y escenarios procedurales en un mundo 3D; biblioteca de planos, luz, atmósfera, voz y exportación con niveles de calidad. |
| **Animate** (Rig y Animate) | Rig humanoide para mallas reales y clips de animación por cuerpo. |
| **Reemplazar personaje** | Sustituye a un personaje en un vídeo a partir de un fotograma editado. |
| **Hoja de estilos** | Estilos H3 importados con su atribución, para que los planos compartan un mismo look. |

## Producción

| Pestaña | Para qué sirve |
| --- | --- |
| **Director** | Planifica y supervisa producciones de varios planos a partir de una historia o canción. |
| **Producciones** / **Obras** | Todas las obras del workspace (videoclip, tráiler, capítulo, historia) con su progreso y **Revisar planos**. |
| **Producciones musicales** | Planos, tomas y montaje de un videoclip; otra toma, usar toma, abrir escena. |
| **Video Editor** | Recorta, divide y reordena clips existentes; la exportación es una tarea FFmpeg en cola. |

Si algo se interrumpe a mitad, entra en **Producciones** y reanuda: no hace falta
empezar de cero.

## Agentes y MCP

Los mismos trabajos están disponibles para agentes externos en
`/api/v1/mcp` (todas las herramientas) y `/api/v1/mcp/series` (solo series). Un
asistente de chat conectado por OAuth puede escribir y producir un capítulo sin
tocar la interfaz: [hacer una serie con ChatGPT](series-lab/CHATGPT_MCP.md).
Conexión y token: [Scene SFX, speech and MCP](development/SCENE_EFFECTS_AND_MCP.md#enable-and-connect-mcp).

## Más guías

- Índice de guías de operador por subsistema: [HOWUSEIT](HOWUSEIT.md).
- Series con un agente de chat: [series-lab/CHATGPT_MCP](series-lab/CHATGPT_MCP.md).
- Tutorial dentro de la app (guía de mantenimiento): [help/HELP_OVERLAY](help/HELP_OVERLAY.md).
- Instalación, requisitos y API HTTP con ejemplos: [README](../README.md).
- Índice de toda la documentación: [docs/README](README.md).
