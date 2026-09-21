# HocusPocus: guía de uso y cobertura del Wizard

Esta guía acompaña la auditoría manual automatizada. Una captura confirma que
una pantalla es accesible; un resultado de generación exige además tarea
completada, archivo publicado y metadatos. El informe conserva esa diferencia.
Las acciones del Wizard indicadas aquí existen en el registro de capacidades;
su presencia no equivale a haber ejecutado cada combinación de modelos.

## Preparar una sesión

1. Arranca HocusPocus desde Pinokio y abre la URL que muestra **Start**.
2. Selecciona una carpeta con **Output**. Las generaciones y conversaciones se
   guardan en esa carpeta. **Workspaces** contiene colecciones de referencias;
   no sustituye a la carpeta de salida.
3. En **Settings**, configura el proveedor del asistente y habilita los modelos
   que quieras usar. Un modelo visible puede requerir una descarga antes del
   primer trabajo. Comprueba **Activity** antes de lanzar otra generación.
4. Abre **Ask to the Wizard**, explica lo que quieres y distingue entre
   «prepáralo sin generar» y «genéralo ahora». Revisa el formulario que rellena.
   Una respuesta de texto del asistente no acredita que el archivo exista.

## Generación directa

| Pantalla | Cómo usarla | Wizard: alcance y ejemplo |
| --- | --- | --- |
| Image | Elige un modelo de imagen, describe la composición y pulsa Generate. El resultado aparece en Media → Images. | `prepare_image`, `start_generation`: «Prepara una imagen de un taller de magos con Flux 2 Klein 4B y genérala». |
| Video → Frames | Elige modelo y duración; añade fotograma o referencias si el modelo las requiere. Describe el movimiento y genera. | `prepare_video`, `start_generation`: «Prepara un plano de un mago programando, rellena el formulario sin generarlo». |
| Video → Multi-Shot | Divide el vídeo en planos y revisa las instrucciones, tiempos y referencias de cada uno antes de generar. | Preparación general de vídeo; comprueba los controles visibles. No se certifica el ajuste individual de cada control mediante una orden genérica. |
| Video → Extend | Selecciona un vídeo de partida y el punto desde el que continuará; describe la continuación. | Preparación general; la selección exacta de fuente y extensión debe revisarse en el formulario. |
| Video → Blend | Añade las referencias necesarias para el modelo y describe la transición. | Preparación general de vídeo; soporte específico depende del modelo. |
| Audio → Speech | Elige un modelo de voz, escribe el texto literal y añade referencia de voz si corresponde. | `prepare_audio`, `start_generation`: «Prepara una locución que diga exactamente “Hola, mundo” en español». |
| Audio → Music | Selecciona un modelo musical, estilo, letra o Instrumental y duración. Write Song ayuda a redactar; Generate sintetiza el audio. | `prepare_audio`, `start_generation`; para canciones ligadas a una historia, usa Story Lab y sus acciones de canción. |
| Audio → SFX | Describe el sonido y configura su duración con un modelo compatible. | `queue_sfx_pack`: «Prepara una colección de efectos de teclado mágico y chispas». Revisa el plan antes de lanzarlo. |
| Audio → Mixer | Añade pistas y ajusta su mezcla con los controles del panel. | No se identifica una capacidad dedicada para todos los controles del mezclador; operación manual. |
| 3D | Elige un generador 3D, añade una imagen válida y genera. Comprueba el GLB en el visor y en Media → 3D. | `prepare_3d`, `start_generation`: «Prepara un objeto 3D a partir de esta imagen con Hunyuan3D Mini Turbo». |

El modelo controla qué entradas acepta y cuánta memoria necesita. La duración
del muestreo no incluye necesariamente la decodificación final: espera al
archivo publicado. Si la tarea queda interrumpida tras un cierre, conserva su
identidad y revisa el consumo antes de reanudarla.

## Edición y herramientas

| Pantalla | Cómo usarla | Wizard |
| --- | --- | --- |
| Edit → Retake | Carga el vídeo y selecciona el tramo que quieres rehacer. Describe el cambio. | No hay una capacidad dedicada `prepare_edit`; usa los controles de edición. |
| Edit → Edit Anything | Añade el medio de partida y las referencias que pida el modelo; describe el resultado. | Manual para los controles específicos de este modo. |
| Edit → Outpaint | Carga el vídeo y amplía el lienzo para crear área nueva. Generate se bloquea si no hay área que completar. | Manual para fuente, encuadre y área. |
| Edit → Repaint | Selecciona la fuente y describe el aspecto del vídeo final. | Manual para los controles específicos. |
| Edit → Recast | Añade vídeo y referencias del personaje que lo sustituirá. Revisa el modelo y los requisitos. | Manual para los controles específicos. |
| Tools → Upscale | Elige imagen o vídeo desde el ordenador o HocusPocus. Selecciona el método y pulsa Upscale. Lanczos cambia el tamaño sin síntesis de detalle por IA. | No hay una capacidad dedicada de upscale en el registro inspeccionado. |
| Tools → Revoice | Selecciona vídeo, modo de uno o dos hablantes y sus muestras de voz. Pulsa la acción de reemplazo. | Manual. |
| Tools → Remove background | Elige una imagen y, si hace falta, aclara qué objeto conservar. Ejecuta y revisa la transparencia. | `remove_background`: «Quita el fondo de esta imagen y conserva el mago». |

## Estudios

| Estudio | Flujo de trabajo | Wizard |
| --- | --- | --- |
| Story Lab | Crea un proyecto, completa premisa, personajes y lugares, genera o edita secciones y guarda. Desde la canción puedes pasar al videoclip. | `create_story`, `update_story`, `generate_story_section`, `configure_story_song`, `generate_story_song`, `stage_story_video`. Ejemplo: «Crea una historia nueva titulada El mago del barrio, completa su premisa y guárdala». |
| Series Lab | Crea una serie y un episodio, prepara el plan de planos, genera los planos y ensambla el episodio. | `create_series_episode`, `generate_series_plan`, `render_series_shots`, `assemble_series_episode`. Pide cada etapa o una producción explícita. |
| Comics | Crea un cómic, define páginas y viñetas, genera y revisa cada panel antes de exportar. | `create_comic`, `generate_comic`, `generate_comic_panel`: «Crea un cómic nuevo de dos páginas sobre un mago programador». |
| Character Creator | Crea un kit de personaje, adjunta referencias consistentes y construye el kit. Usa después sus vistas o rig en otros estudios. | `create_character_kit`, `attach_character_kit_references`, `build_character_kit`. |
| Video 2.5D | Crea una escena de capas, añade imágenes, anima cámara y capas, ajusta el ritmo, guarda y exporta. | `create_3d_scene`, `add_3d_scene_layer`, `apply_3d_rhythm`, `save_3d_scene`, `export_3d_scene`. Estas acciones se refieren a **2.5D**, aunque sus identificadores incluyan `3d`. |
| Video 3D | Monta objetos GLB en un mundo, ajusta escala y cámara, elige las animaciones disponibles y sus recorridos, previsualiza, guarda la escena y exporta. Exporta o importa un tipo de escenario desde **Biblioteca de planos → Mis escenarios** (`.world3d.template.json`). Eso no sustituye el JSON de un plano ni empaqueta los GLB. | En el registro inspeccionado no hay capacidades dedicadas para montar GLB y ajustar las cámaras de este editor. Hazlo manualmente. |
| Replace character | Selecciona el vídeo y un fotograma editado que muestre la sustitución. Revisa los ajustes y genera. | Manual. |
| Animate | Abre un personaje compatible, revisa su rig y selecciona la animación con los controles del estudio. | `open_character_kit_rig` abre el rig del kit; la edición completa de animación requiere controles manuales. |

En el editor de la PR #257, selecciona un objeto y trabaja dentro del visor:
**G** mueve, **R** rota alrededor del eje Y y **S** cambia su escala uniforme.
La ayuda traducida aparece durante la interacción y desaparece al soltar o
salir. Estos atajos no interceptan lo que escribes en un campo de texto.

Las plantillas cinematográficas de la PR #257 amplían Video 3D con primeros
planos, persecuciones y planos de coche. La animación de caminar o correr debe
acompañarse de un recorrido para desplazarse por el escenario. Un GLB sin rig
ni piezas separadas puede trasladarse como objeto completo, pero eso no crea
ruedas articuladas ni zonas de pintura independientes.

En Series Lab, crear el episodio prepara sus datos iniciales. Para disponer de
planos, pide después «genera el plan completo de este episodio, sin renderizar».
Espera a que la tarea termine y pide «aplica la propuesta completada con este
jobId». El flujo inspeccionado no espera automáticamente entre generar y
aplicar cuando el Wizard propone ambas acciones seguidas en una sola respuesta.

## Producción

| Pantalla | Cómo usarla | Wizard |
| --- | --- | --- |
| Director | Envía una historia o canción concreta, prepara el plan, revisa escenas y lanza la producción. Sigue la tarea hasta el MP4 final. | `stage_story_video`, `stage_story_music_video`, `start_director_production`. Identifica título y canción para evitar usar otra selección. |
| Video Editor | Crea un proyecto, añade vídeos, recorta clips, añade audio y exporta el montaje. | `create_video_editor_project`, `add_video_editor_clips`, `trim_video_editor_clip`, `add_video_editor_audio`, `export_video_editor`. Ejemplo: «Monta estos dos vídeos en este orden, añade esta canción y exporta». |
| Productions | Consulta las producciones existentes y abre sus resultados o tareas. | Consulta y navegación parciales; la generación se inicia en el estudio o en Director. |

## Biblioteca, organización y seguimiento

| Pantalla o filtro | Uso | Wizard |
| --- | --- | --- |
| Media → Projects | Abre proyectos guardados y retoma su edición. | Navegación y selección dependen del tipo de proyecto; no asumas que un filtro equivale a una acción de producción. |
| Media → Assets | Busca referencias reutilizables y elige la identidad exacta del asset. | Puede trabajar con assets identificados por las capacidades correspondientes; revisa la selección. |
| All, Images, Videos, Audio, 3D | Filtra los archivos publicados por tipo. | Navegación parcial; los filtros pueden ajustarse manualmente. |
| Videoclips, Trailers, Episodes | Encuentra resultados clasificados por tipo de producción. | Pide preparar o producir desde Story/Director/Series; el filtro sirve para consultar resultados. |
| Scenes, Style sheet | Localiza escenas y material de estilo guardado. | 2.5D dispone de guardar/seleccionar escena. El resto depende del editor correspondiente. |
| Edits, Multi-clip, Favorites | Filtra por edición, montaje o favorito. | Ajuste manual de filtros y favoritos cuando no haya una capacidad específica. |
| Workspaces | Crea colecciones de referencias y notas conservando los IDs de sus assets. | `create_workspace_collection`, `update_workspace_collection`. No es lo mismo que cambiar Output. |
| Activity | Consulta cola, recursos y errores; abre detalles de una tarea antes de cancelarla o reintentarla. | `inspect_queue`, `cancel_task`, `retry_task`, `resume_task`. Ejemplo: «Muestra las tareas de esta carpeta y explica cuál sigue activa». |
| Settings | Configura idioma, apariencia, modelos, proveedores y almacenamiento. | Navegación y descarga de modelos (`download_model`) parciales; credenciales y preferencias se revisan manualmente. |

## Cómo repetir y leer la auditoría

Sigue [WIZARD_ACCEPTANCE_TESTING.md](WIZARD_ACCEPTANCE_TESTING.md). Cada intento
guarda su propio informe, capturas, traza y resultados; no sobreescribe intentos
anteriores. `app-tour` recorre las pantallas. `app-generate` ejecuta casos de
generación y herramientas y requiere el perfil `real` con `--confirm-real`.

Comprueba por separado: navegación, generación, persistencia, exportación y
ejecución desde el Wizard. Un caso fallido sigue siendo evidencia útil: no se
elimina ni se transforma en éxito al repetirlo. La cobertura de una familia de
funciones tampoco certifica todos sus modelos, proveedores o parámetros.
