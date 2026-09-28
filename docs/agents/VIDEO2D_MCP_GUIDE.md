# Video 2D por MCP

Un agente puede montar una escena Video 2D sin leer el código de la UI. Los ids
salen de los catálogos compartidos en `app/shared/`. Cada llamada va versionada:
`{version: 1, input: {...}}`.

El camino mínimo son cinco llamadas: catálogo, compilar, validar, guardar y
exportar. El rótulo, la letra y el montaje se añaden en el mismo recorrido
cuando la escena los necesita. `scenes.video2d.preview` guarda la hoja de
contactos como PNG del workspace y devuelve su URL; no metas los bytes en el
JSON. La llamada que sigue a compilar (y a pegar rótulo o letra) es
`scenes.video2d.validate`. No guarda. Las respuestas largas llegan en resumen;
pide `detail: true` o `full: true` solo cuando necesites el documento.

Nada de esto genera medios en GPU. Los assets tienen que ser ya URLs durables
del workspace (`/api/v1/file/...`, `/api/v1/uploads/...`) o de ejemplos
(`/examples/...`).

## 1. Catálogo — `scenes.catalog`

Descubre ids. No guarda. `kind` es uno de: `templates`, `text`, `finish`,
`fonts`, `atmospheres`, `motion`, `effects`.

- `templates` → `app/shared/scene_templates.json`
- `text` → `app/shared/text_templates.json`
- `finish` → `app/shared/finish_presets.json`
- `fonts` → `app/shared/fonts.json`
- `atmospheres` → `app/shared/atmospheres.json`
- `motion` → `app/shared/motion_presets.json` (movimientos y cámaras)
- `effects` → `app/shared/scene_effects.json` (efectos de pantalla)

```json
{
  "version": 1,
  "input": {
    "kind": "templates"
  }
}
```

Repite la llamada con `"kind": "text"` antes de elegir un rótulo. Sin `detail`,
cada fila es `id`, `name`, una descripción de una línea y `counts` (no el
esquema de `controls`). Pide `"id": "cinema-establishing"` o `"detail": true`
para slots y controles. Copia esos ids; no los inventes.

## 2. Compilar la plantilla — `scenes.template.compile`

No guarda. Sin `full` devuelve ids de capas, códigos de aviso, duración y tamaño.
Con `"full": true` devuelve `{document, warnings}`. `templateId` es un id real de
`scene_templates.json`. `assets` asigna cada slot de esa plantilla a un medio
durable. `controls` usa solo controles que el catálogo declara para ese id.

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
    "fps": 30,
    "full": true
  }
}
```

El `document` (solo con `full: true`) es la escena editable. Los avisos no
impiden seguir, pero hay que leer sus códigos. La vista previa es opcional y
devuelve una URL, no el PNG.

## 3. Rótulo — `scenes.text.template`

No guarda. Sin `full` devuelve los ids de los rótulos. Con `"full": true` devuelve `{texts}`. `templateId` es un id real de
`text_templates.json`. `fields` usa las claves de ese id (`title-card` tiene
`title` y `subtitle`). Pega el array `texts` en `document.texts` antes de
validar.

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
    "height": 720,
    "full": true
  }
}
```

Si la escena no lleva rótulo, omite esta llamada.

## 4. Letra — `scenes.lyrics.import`

No guarda. Sin `full` devuelve ids de líneas y duración. Con `"full": true` devuelve `{lyrics}`. `format` es `srt`, `lrc`, `plain` o
`timing-bundle`. `text` es el contenido (en `timing-bundle`, el JSON del bundle
serializado como texto). Pega el objeto `lyrics` en `document.lyrics`.

```json
{
  "version": 1,
  "input": {
    "format": "plain",
    "text": "The bird is freed\nKeep the line",
    "full": true
  }
}
```

Si no hay letra que mostrar, omite esta llamada.

## 5. Validar — `scenes.video2d.validate`

Esta es la llamada que sigue a compilar. No guarda. Sin `full` devuelve ids,
códigos de error y de aviso, duración y tamaño. Con `"full": true` devuelve
`{document, errors, warnings}`. `document` es el de compile, más `texts` y
`lyrics` si los hubo. Si `errors` no está vacío, corrige y vuelve a validar.
No exportes ni guardes una escena con errores.

```json
{
  "version": 1,
  "input": {
    "workspace": "demo-video2d",
    "full": true,
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

Usa el `document` devuelto por validate en las dos llamadas siguientes.

## 6. Guardar — `scenes.document.save`

Crea una revisión inmutable (`*.scene.json`) en el workspace. No exporta. El
resultado trae `name`: ese nombre es el que cita el montaje. Un `intent_id`
opcional en el sobre, si se repite con el mismo documento, devuelve esa
revisión y no escribe otro archivo. No hace falta en el catálogo.

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

## 7. Exportar — `scenes.video2d.export`

Renderiza el MP4 en la CPU. No es la vista previa. El sobre lleva `intent_id`
además de `version` e `input`. Reutiliza el mismo `intent_id` solo para leer el
recibo con `scenes.video2d.export.receipt` (`input.workspace` e
`input.intent_id`). El MP4 publicado es el `source` del clip; no inventes el
nombre del archivo.

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

## 8. Montaje — `montages.save`

Coloca el MP4 en una línea de tiempo editable. No renderiza. `clips[].source`
es el archivo que devolvió el recibo de exportación. `origin.scene` es el
`name` que devolvió `scenes.document.save`. Crear el mismo nombre otra vez
responde `409 exists`; para actualizar hay que pasar `file` y
`expected_revision`.

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
