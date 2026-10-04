# Hacer una serie con ChatGPT conectado a HocusPocus

HocusPocus expone sus herramientas por MCP. Un agente como ChatGPT puede escribir y producir un capítulo de una serie de
Series Lab, con personajes, voces, render, versión en otro idioma y montaje, sin tocar la interfaz.

## Qué hay preparado

- **Perfil `series`:** `/api/v1/mcp/series` sirve solo las ~60 herramientas que hacen falta para una serie, frente a las
  ~160 del endpoint completo. Sus primeras instrucciones dicen al agente que empiece por `series.guide`.
- **`series.guide`:** devuelve la guía de trabajo (pasos, formato de plano, convenciones de calidad, errores conocidos) y,
  con `series_id`, la biblia viva de la serie:
  - personajes con su kit, poses y voces por idioma;
  - localizaciones con variantes, anclas y fondo 3D;
  - los ficheros de música y efectos del espacio de trabajo;
  - los episodios hechos y el prefijo de ids del siguiente.

  El texto fijo de la guía está en `app/shared/series_agent_guide.md`.
- **`series.episode.get`:** un episodio en forma compacta, para copiar el estilo de un capítulo anterior sin leer la serie entera.
- **`series.episode.from_script`:** el agente escribe el capítulo entero como un guion compacto en todos los idiomas a la
  vez: escenas, planos, reparto con pose y posición, frases con pausas, carteles, música, efectos de sonido y de pantalla
  con su momento, atrezo, ritmo y planos 3D con diálogo. Antes de escribir nada lo comprueba contra la biblia y devuelve
  todos los errores juntos (`check: true` solo comprueba). Pone los ids del episodio y crea las versiones de idioma.
- **`series.episode.produce`:** una llamada lo hace todo en el servidor. Renderiza el original y cada idioma, aprueba las
  tomas, reintenta una vez los planos que fallan y monta cada capítulo con subtítulos. Se consulta con
  `series.episode.produce.status`, que lista los ficheros finales; se puede parar y reanudar.
- **OAuth 2.1:** los conectores de ChatGPT no aceptan una clave fija; solo OAuth con PKCE. HocusPocus incluye un servidor
  OAuth mínimo para una persona: descubrimiento (`/.well-known/...`), registro dinámico del cliente, página de autorización
  donde escribes una vez la clave MCP, y tokens propios del cliente que caducan, se renuevan y quedan ligados al perfil.
  Rotar la clave o desactivar el acceso anula todos los tokens.

## Conectar ChatGPT

1. **Activa el acceso de agentes** en HocusPocus (Ajustes → MCP) y copia la clave. Con `HOCUS_MCP_TOKEN` en el entorno se
   usa esa. Mejor una instancia aparte para el agente que la que usas a diario.
2. **Publícala por HTTPS.** ChatGPT se conecta desde internet, no desde tu red. Por ejemplo, con un túnel de Cloudflare:

   ```bash
   cloudflared tunnel --url http://127.0.0.1:42003
   ```

   Esto da una URL `https://<algo>.trycloudflare.com`. HocusPocus deduce su dirección pública de las cabeceras del túnel.
   Si se equivoca, fíjala con `HOCUS_PUBLIC_URL=https://<algo>.trycloudflare.com` antes de arrancar.
3. **Crea el conector en ChatGPT.** Los nombres de los menús cambian con las versiones:
   - activa el modo desarrollador en *Ajustes → Apps y conectores → Avanzado*;
   - crea un conector con la URL `https://<algo>.trycloudflare.com/api/v1/mcp/series` y autenticación **OAuth**.
4. **Autoriza.** ChatGPT se registra solo y abre la página *Conectar con HocusPocus*. Escribe ahí la clave MCP. ChatGPT
   nunca ve la clave: recibe su propio token, válido solo para el perfil `series`.

Para cortar el acceso: rota la clave o desactiva el acceso en Ajustes → MCP y cierra el túnel.

## Instrucciones recomendadas para el proyecto de ChatGPT

> Usas HocusPocus por el conector MCP. Antes de nada, llama a `series.guide` con `workspace: "<espacio>"` y
> `series_id: "<serie>"` y sigue la guía: usa solo los personajes, poses, localizaciones y ficheros de audio de la biblia.
> Lee con `series.episode.get` el último episodio para copiar su estilo. Escribe el capítulo con
> `series.episode.from_script` (primero con `check: true`) y prodúcelo con `series.episode.produce`; consulta
> `series.episode.produce.status` cada uno o dos minutos hasta que termine. Ante un error, lee el mensaje y corrige la
> llamada; no inventes ids.

Un encargo típico: *«Escribe y produce el capítulo 3 de Valle Inquietante: Kevin intenta… En español y en inglés, con
subtítulos. Enséñame el guion antes de renderizar.»*

## Límites de hoy

- Un capítulo de 50 planos tarda (de una a varias horas según la GPU). Pide primero el guion, revisa el resultado de
  `check` y prueba con dos o tres planos (`series.episode.render_native` con `shot_ids`) antes de producirlo entero.
- Los personajes, localizaciones y sonidos nuevos siguen siendo varias herramientas por elemento (imagen, recorte, rig,
  voz). Para un capítulo con el reparto existente no hace falta.
- ChatGPT no ve vídeo. Puede pedir fotogramas con `scenes.video2d.preview` y fiarse de las comprobaciones automáticas de
  voz (`qa.speech`).
