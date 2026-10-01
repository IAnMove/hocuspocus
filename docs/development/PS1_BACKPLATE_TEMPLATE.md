# Escena estilo PS1: gráficos prerenderizados

El template **Escena estilo PS1** reutiliza la composición de
la muestra PS1: imagen fija como entorno y un personaje GLB animado. El lugar, la
paleta, la actuación y los cortes los decide el autor o el LLM. La escena conserva
`templateId: "two-shot"` como formato nativo compatible; el identificador de
biblioteca **`hocuspocus/ps1-backplates`** es independiente y se conserva al cambiar
el nombre visible. Usa el renderer existente.

Se llama **Escena estilo PS1**. No hace falta escribir el nombre exacto ni el id: `templates.list`
busca por palabras sueltas (sin distinguir mayúsculas, tildes ni plurales, en cualquier orden, y una
frase entera vale) y devuelve los resultados ordenados; sin `query` lista todo. Un asistente con acceso
a la biblioteca debe listar, elegir por título y descripción lo que encaje con la petición, consultar los
recursos con `templates.get` y usar el id devuelto para aplicar la composición:

> Haz un videoclip con escenas con gráficos prerenderizados, estilo PS1. Busca
> «Escena estilo PS1» en la biblioteca: fondos de Qwen Image 2.1, personajes 3D
> animados y cámara fija. Usa mi canción y mis personajes. Muéstrame los fondos
> y la propuesta de planos para revisión antes de exportar.

## Importar y usar en la interfaz

1. Importa el archivo `.hptemplate` en **Video 3D → Mis plantillas → Importar**.
   Revisa nombre, recursos y controles; confirma la importación. Aparecerá la ficha
   **Escena estilo PS1**, con la miniatura incluida en el paquete. Si ya importaste
   la versión anterior, revisa y confirma su reemplazo para actualizar el nombre
   y sus términos de búsqueda; las escenas guardadas conservan su documento.
2. Selecciona la ficha. La escena avisa de los recursos que faltan: `background`
   (imagen) y `actor` (GLB). Asigna tus archivos desde el editor. Elige una animación
   que exista en el GLB; `Walking`, índice 0, sólo describe el personaje de la muestra.
3. Ajusta escala, recorrido, duración, cámara fija y luz en los controles normales
   de Video 3D. Guarda la escena y vuelve a abrirla desde la biblioteca de escenas.
   Se conserva la combinación editada. Guardar una escena y guardar otro template
   son operaciones distintas: un nuevo template sin medios vacía sus recursos.

La ficha no genera imágenes ni descarga modelos. La miniatura se reutiliza de un
fotograma existente; una combinación nueva de fondo y personaje sigue necesitando
revisión visual. El paquete no incluye el fondo ni el GLB de la producción.

## Crear el paquete sin GPU

La definición versionada está en
`pinokio_agent/skills/api/hocuspocus/clients/ps1_backplates_template.json`.
Desde la raíz del repositorio, con un fotograma existente:

```sh
python pinokio_agent/skills/api/hocuspocus/clients/backplate_template.py \
  --preview /ruta/a/fotograma-existente.png \
  --output ps1-backplates.hptemplate
```

El cliente sólo necesita Python estándar. La vista previa admite PNG/JPEG/WebP de
hasta 2 MB. El mismo JSON y la misma vista previa producen un ZIP idéntico; los
medios y pesos quedan fuera del repositorio. El nombre de salida debe ser nuevo.
Para importar además en una instancia, añade `--base-url "$HOCUS_API_URL"` usando
la URL descubierta de esa instancia. Se hace preflight y se rechaza sobrescribir
un template existente. La importación manual de la interfaz permite revisar una
reemplazación cuando corresponde.

## Uso mediante LLM / MCP

La interfaz y los agentes comparten `templates.list`, `templates.get`,
`templates.import` y `templates.apply`. Una vez importado el paquete:

```json
{"version":1,"input":{"editor":"video3d","query":"escenas con gráficos prerenderizados"}}
```

Usa ese sobre con `templates.list`, y consulta `templates.get` con
`{"version":1,"input":{"id":"hocuspocus/ps1-backplates"}}`.
El manifiesto declara recursos, controles y un prompt breve en la ayuda del fondo.
Para `templates.apply`:

```json
{
  "version": 1,
  "input": {
    "id": "hocuspocus/ps1-backplates",
    "workspace": "mi-videoclip",
    "slots": {
      "background": "/api/v1/file/estacion.png?workspace=mi-videoclip",
      "actor": "/api/v1/file/robot.glb?workspace=mi-videoclip"
    },
    "controls": {
      "duration": 8, "start_x": -1.4, "end_x": 1, "end_z": -0.5,
      "actor_scale": 1, "clip_index": 0, "clip_name": "Walking", "clip_speed": 0.8,
      "light_color": "#ffdbad", "light_intensity": 1.5
    }
  }
}
```

El índice de clip debe ser entero y existir en el modelo. El manifiesto también
expone `start_y/z`, `end_y`, `face_travel`, `camera_x/y/z`, `look_x/y/z`,
`camera_fov` y `light_x/z`. Cambiar la posición fija de cámara sirve para alinear
perspectivas; no añade movimiento durante el plano.

`templates.apply` devuelve un documento y `missingSlots`; comprueba que no falta
ningún recurso. Guarda con `scenes.document.save` y reabre con
`scenes.document.get`. Para una producción, úsalo como
`{"kind":"scene3d","scene3d":{"document":DOCUMENTO}}`, con el estilo
`ps1-backplates`; su validación sigue actuando antes de iniciar trabajo.
Para exportar usa `scenes.world3d.export`. Conserva documentos, fuentes y recibos.

## Prompt de ejemplo para nuevos fondos

Modelo: **Qwen Image 2.1**, normalmente 40 pasos. Genera el fondo a la resolución
de origen que permita el equipo y conserva ese archivo; la escena inicial de
ejemplo es 1280×720. Generar el fondo es una acción posterior que requiere GPU:
el importador de templates nunca ejecuta ese paso.

```text
Empty architectural environment, no people, no characters, no animals,
no silhouettes, no statues shaped like people.
A prerendered background for a late-1990s PlayStation adventure game:
an abandoned railway station at blue hour, moss-green tiles, amber lamps,
distant mountains and a quiet melancholic atmosphere.
Single fixed elevated three-quarter camera, natural perspective,
approximately 45-degree field of view. Visible flat walkable foreground
across the lower third; a clear unobstructed route from left to right.
Warm light comes from the upper left; consistent shadows and color.
Rich painted textures, restrained cinematic detail, crisp readable
architecture, 16:9 composition. No foreground obstacles covering the route,
no text, no logos, no HUD, no border.
Background only; the animated 3D character will be added separately.
```

Cambia lugar, paleta, hora y dirección de luz; la versión con marcadores está en
`backgroundPrompt` de la definición JSON. La imagen no garantiza una calibración
3D exacta: revisa horizonte, suelo y perspectiva, y ajusta cámara y personaje.
Para otra vista, crea otro fondo y otro plano con cámara fija.

## Aceptación y límites

- Importar el paquete presenta ficha, recursos y miniatura tanto por HTTP como
  por `templates.list/get`; seleccionarlo en la UI aplica un documento válido.
- Una búsqueda con otras palabras («escenas estilo PS1», «PS1 style scene», «escena de gráficos
  prerenderizados») devuelve la misma ficha y el mismo id, también tras exportar y volver a importar.
- Cambiar fondo, GLB, animación y recorrido, guardar y reabrir conserva esos cambios.
- Exportar/importar el template en una biblioteca nueva conserva los controles y
  el recorrido sin incluir archivos privados. Los recursos pendientes son visibles.
- Tipos de recursos incorrectos, duraciones/escala fuera de rango y controles
  desconocidos se rechazan antes de llamar a un renderer.

Las pruebas son de biblioteca, API y editor sin GPU. No evalúan calidad artística,
contacto de pies, sombras ni oclusión. El fondo pintado no aporta colisiones,
profundidad ni máscaras para caminar detrás de objetos. Un render o una prueba
técnica correctos no aprueban una nueva composición artística.
