# Video 2D por MCP

Un agente puede montar una escena Video 2D sin leer el código de la UI. Los ids
salen de los catálogos compartidos en `app/shared/`. Cada llamada va versionada:
`{version: 1, input: {...}}`.

El recorrido es: catálogo, inspeccionar el asset, compilar, rótulo, letra,
editar, validar, vista previa, guardar, exportar y montar. Nada de esto genera
medios en GPU. Los assets tienen que ser ya URLs durables del workspace
(`/api/v1/file/...`, `/api/v1/uploads/...`) o de ejemplos (`/examples/...`).

## 1. Catálogo — `scenes.catalog`

Descubre ids. No guarda. `kind` es uno de: `templates`, `text`, `finish`,
`fonts`, `atmospheres`, `motion`, `effects`, `graphics`.

- `templates` → `app/shared/scene_templates.json`
- `text` → `app/shared/text_templates.json`
- `finish` → `app/shared/finish_presets.json`
- `fonts` → `app/shared/fonts.json`
- `atmospheres` → `app/shared/atmospheres.json`
- `motion` → `app/shared/motion_presets.json` (movimientos y cámaras)
- `effects` → `app/shared/scene_effects.json` (efectos de pantalla)
- `graphics` → `app/shared/scene_graphics.json` (gráficos con id y parámetros, sin código)

```json
{
  "version": 1,
  "input": {
    "kind": "templates"
  }
}
```

Repite la llamada con `"kind": "text"` antes de elegir un rótulo y con
`"kind": "finish"` antes de `set_finish`. La respuesta es el JSON del catálogo:
objetos con `id`. Copia esos ids; no los inventes.

## 2. Inspeccionar — `scenes.assets.inspect`

Describe ficheros que ya están en el workspace (tamaño, alfa, duración). No
genera medios. `names` son como máximo 20 nombres de fichero, no rutas.

```json
{
  "version": 1,
  "input": {
    "workspace": "demo-video2d",
    "names": ["plate.png"]
  }
}
```

Si el asset es una URL `/examples/...` ya publicada, puedes saltar esta llamada
y pasar esa URL a compilar.

## 3. Compilar la plantilla — `scenes.template.compile`

No guarda. Devuelve `{document, warnings}`. `templateId` es un id real de
`scene_templates.json`. `assets` asigna cada slot de esa plantilla a un medio
durable. `controls` usa solo controles que el catálogo declara para ese id.
`documentary-history` admite como máximo 12 s; si el documento se estira
después, validar avisa `empty_timespan`.

```json
{
  "version": 1,
  "input": {
    "templateId": "trailer-teaser",
    "controls": {
      "duration": 4,
      "intensity": 0.6
    },
    "assets": {
      "hero": "/examples/hero.png",
      "plate": "/examples/plate.png"
    },
    "width": 1280,
    "height": 720,
    "duration": 4,
    "fps": 30
  }
}
```

El `document` devuelto es la escena editable. Los avisos no impiden seguir, pero
hay que leerlos.

## 4. Rótulo — `scenes.text.template`

No guarda. Devuelve `{texts}`. `templateId` es un id real de
`text_templates.json`. `fields` usa las claves de ese id (`title-card` tiene
`title` y `subtitle`). Editar puede aplicar el mismo id con `add_title`, que
sustituye los cues con el mismo id.

```json
{
  "version": 1,
  "input": {
    "templateId": "title-card",
    "fields": {
      "title": "Musktopia",
      "subtitle": "Un puerto"
    },
    "start": 0.4,
    "duration": 3.2,
    "width": 1280,
    "height": 720
  }
}
```

`title-card` deja el título cerca de y=46 y el subtítulo cerca de y=62. No lo
pegues encima de una letra que siga en y=78. Si la escena no lleva rótulo, omite
esta llamada.

## 5. Letra — `scenes.lyrics.import`

No guarda. Devuelve `{lyrics}`. `format` es `srt`, `lrc`, `plain` o
`timing-bundle`. `text` es el contenido (en `timing-bundle`, el JSON del bundle
serializado como texto). El estilo por defecto usa y=78. Si el rótulo también
vive ahí (por ejemplo el pie de `lower-third-date`), baja o sube `style.y`
antes de validar.

```json
{
  "version": 1,
  "input": {
    "format": "plain",
    "text": "The bird is freed\nKeep the line"
  }
}
```

Si no hay letra que mostrar, omite esta llamada.

## 6. Editar — `scenes.video2d.edit`

No guarda ni renderiza. `operations` es una lista (máximo 32). `set_finish`
copia un id de `finish_presets.json`. `add_title` construye los cues de un id
de `text_templates.json`. `reorder` asigna z 0, 10, 20… en el orden nuevo y
debe ser una permutación de los ids de capa. Las cámaras de `add_layer` salen
de los ids `kind: camera` de `motion_presets.json`.

`update_layer` puede llevar `patch.focus` con `{x, y}` de 0 a 100: es el punto
del marco de la capa que permanece en el ancla mientras cambia `scale`. Sin
`focus`, o con `{50, 50}`, la escala sigue alrededor del centro y las escenas
ya guardadas no se mueven. Un zoom a una esquina no necesita una posición fuera
del rango de `animation` (`x = 50 - (fx - 50) * scale` lo resuelve el pintor).

```json
{
  "version": 1,
  "input": {
    "document": {
      "version": 1,
      "name": "teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "duration": 4,
      "layers": [
        {
          "id": "plate",
          "type": "image",
          "source": "/examples/plate.png"
        }
      ]
    },
    "operations": [
      {
        "op": "set_finish",
        "preset": "warmCinema"
      },
      {
        "op": "add_title",
        "template": "chapter",
        "fields": {
          "kicker": "PART",
          "title": "Harbour"
        },
        "start": 0.4,
        "duration": 3.2
      },
      {
        "op": "reorder",
        "ids": ["plate"]
      }
    ]
  }
}
```

`add_title` con `chapter` coloca el kicker en y=40 y el título en y=50, lejos
de una letra en y=78.

## 7. Validar — `scenes.video2d.validate`

No guarda. Devuelve `{document, errors, warnings}`. Si `errors` no está vacío,
corrige y vuelve a validar. No exportes ni guardes una escena con errores.

Las cajas de texto y de letra usan fuente, tamaño, `maxWidth`, alineación y el
padding de `box`. `align: left` apoya el borde izquierdo en `x` y `align: right`
el derecho. `center`, o la ausencia de `align`, siguen centrados en el ancla.
El ancla puede estar dentro y la caja no: `text_outside_frame` usa esa caja.
Avisos estables:

```json
{
  "warnings": [
    {
      "code": "text_overlap",
      "path": "texts[0]",
      "message": "texts[0] overlaps texts[1]."
    },
    {
      "code": "text_outside_frame",
      "path": "texts[1]",
      "message": "Text box extends outside the frame."
    },
    {
      "code": "lyrics_overlap",
      "path": "lyrics.lines[0]",
      "message": "lyrics.lines[0] overlaps texts[1]."
    },
    {
      "code": "empty_timespan",
      "path": "duration",
      "message": "No visible layer or text from 12s to 20s.",
      "start": 12,
      "end": 20
    },
    {
      "code": "reserved_zone",
      "path": "texts[0]",
      "message": "texts[0] enters reserved zone counter.",
      "zone": "reservedZones[0]"
    },
    {
      "code": "text_low_contrast",
      "path": "texts[0]",
      "message": "texts[0] contrast is 1.00:1, under 3:1.",
      "ratio": 1.0
    }
  ]
}
```

`text_low_contrast` solo aparece si el pintor de la hoja de contactos puede
arrancar y el muestreo de píxeles queda por debajo de 3:1. Si Playwright o
`ui/dist/scene2d-render.html` no están, no se inventa un ratio.
`reservedZones` es una lista opcional `{id, x, y, width, height}` en porcentaje
del frame (por ejemplo un contador arriba a la derecha). `empty_timespan` es un
tramo de más de 2 s sin capa visible (`image`, `video`, `overlay`, `model3d`,
`effect`) y sin textos.

El documento de ejemplo no apila el rótulo sobre la letra: el capítulo queda
en el centro y la letra en y=78.

```json
{
  "version": 1,
  "input": {
    "workspace": "demo-video2d",
    "document": {
      "version": 1,
      "name": "teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "duration": 4,
      "layers": [
        {
          "id": "plate",
          "type": "image",
          "source": "/examples/plate.png"
        },
        {
          "id": "cam",
          "type": "camera"
        }
      ],
      "texts": [
        {
          "id": "kicker",
          "text": "PART",
          "start": 0.4,
          "end": 3.6,
          "preset": "impact",
          "x": 50,
          "y": 40,
          "size": 3,
          "font": "condensed"
        },
        {
          "id": "chapter",
          "text": "Harbour",
          "start": 0.4,
          "end": 3.6,
          "preset": "impact",
          "x": 50,
          "y": 50,
          "size": 8,
          "font": "display"
        }
      ],
      "lyrics": {
        "mode": "karaoke",
        "lines": [
          {
            "id": "line-1",
            "start": 0.2,
            "end": 3.8,
            "words": [
              {
                "text": "Harbour",
                "start": 0.2,
                "end": 3.8
              }
            ]
          }
        ],
        "style": {
          "font": "sans",
          "size": 5,
          "color": "#f4efe6",
          "activeColor": "#ffe08a",
          "x": 50,
          "y": 78,
          "maxWidth": 70,
          "align": "center",
          "visibleLines": 1
        }
      },
      "reservedZones": [
        {
          "id": "counter",
          "x": 78,
          "y": 0,
          "width": 22,
          "height": 12
        }
      ]
    }
  }
}
```

Usa el `document` devuelto por validate en las llamadas siguientes.

## 8. Vista previa — `scenes.video2d.preview`

Pinta hasta 8 instantes y devuelve una hoja de contactos PNG. No guarda la
escena ni escribe un MP4. No usa la GPU: el pintor va por el carril CPU
`scene2d-render`. Cada tiempo está entre 0 y `duration`. `input.workspace` es
opcional y usa la misma cadena que validate y export. Quien no lo envía sigue
igual: la hoja sale de `document` y `times`.

```json
{
  "version": 1,
  "input": {
    "document": {
      "version": 1,
      "name": "teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "duration": 4,
      "layers": [
        {
          "id": "plate",
          "type": "image",
          "source": "/examples/plate.png"
        }
      ]
    },
    "times": [0.4, 2]
  }
}
```

## 9. Guardar — `scenes.document.save`

Crea una revisión inmutable (`*.scene.json`) en el workspace. No exporta. El
resultado trae `name`: ese nombre es el que cita el montaje.

```json
{
  "version": 1,
  "input": {
    "workspace": "demo-video2d",
    "name": "teaser",
    "document": {
      "version": 1,
      "name": "teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "duration": 4,
      "layers": [
        {
          "id": "plate",
          "type": "image",
          "source": "/examples/plate.png"
        },
        {
          "id": "cam",
          "type": "camera"
        }
      ]
    }
  }
}
```

## 10. Exportar — `scenes.video2d.export`

Renderiza el MP4 en la CPU. No es la vista previa. El sobre lleva `intent_id`
además de `version` e `input`. Reutiliza el mismo `intent_id` solo para leer el
recibo con `scenes.video2d.export.receipt` (`input.workspace` e
`input.intent_id`). Ese recibo copia el `status` de la tarea: no se queda en
`queued` cuando el MP4 ya existe. `receipt.artifacts` es entonces
`[{name, url, workspace}]` del archivo publicado. La admisión guardada no
cambia. El MP4 publicado es el `source` del clip; no inventes el nombre del
archivo.

```json
{
  "version": 1,
  "intent_id": "teaser-export-1",
  "input": {
    "workspace": "demo-video2d",
    "document": {
      "version": 1,
      "name": "teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "duration": 4,
      "layers": [
        {
          "id": "plate",
          "type": "image",
          "source": "/examples/plate.png"
        },
        {
          "id": "cam",
          "type": "camera"
        }
      ]
    }
  }
}
```

La exportación headless admite capas `image`, `video`, `overlay`, `effect` y
`camera`. Rechaza `model3d`.

## 11. Montaje — `montages.save`

Coloca el MP4 en una línea de tiempo editable. No renderiza. `clips[].source`
es el archivo que devolvió el recibo de exportación. `origin.scene` es el
`name` que devolvió `scenes.document.save`. Crear el mismo nombre otra vez
responde `409 exists`; para actualizar hay que pasar `file` y
`expected_revision`. `montages.export.status` acepta `input.workspace`
opcional, igual que el resto de comandos de montaje, y sigue funcionando solo
con `job_id`.

```json
{
  "version": 1,
  "input": {
    "workspace": "demo-video2d",
    "montage": {
      "version": 1,
      "name": "Teaser",
      "width": 1280,
      "height": 720,
      "fps": 30,
      "clips": [
        {
          "id": "c1",
          "source": "teaser.mp4",
          "trimStart": 0,
          "trimEnd": 0,
          "origin": {
            "kind": "scene2d",
            "scene": "teaser-0123456789.scene.json"
          }
        }
      ]
    }
  }
}
```

`source` y `scene` del ejemplo son marcadores: sustitúyelos por el MP4 del
recibo y por el `name` real del guardado.
