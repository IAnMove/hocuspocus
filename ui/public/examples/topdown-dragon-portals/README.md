# El portal del dragón

Plantilla World3D `topdown-dragon-portals`, en Cine / Dark Fantasy.

La capa del dragón reproduce un vídeo con transparencia. El paisaje lejano y los dos acantilados tienen movimientos independientes. El portal muestra el destino, gira al abrirse y crece delante del dragón para ocultarlo durante la entrada. La explosión y las chispas tienen su propia posición y duración.

En el editor puedes seleccionar:

- **dragon-knight**: sustituir el vídeo del personaje o ajustar su avance.
- **destination-gate**: cambiar la imagen del destino y las posiciones, giros y escalas de la apertura.
- **crossing-burst / crossing-sparks**: ajustar el momento y la intensidad de la explosión.
- **left-cliff / right-cliff / distant-gorge**: cambiar los escenarios y su movimiento por capas.

Los recursos proceden de las herramientas de generación de HocusPocus. El dragón usa MiniMax H3 y la herramienta Quitar fondo; las imágenes de los reinos usan MiniMax Image. El montaje de los tres reinos se guarda además como escenas editables en la biblioteca, con portales de llegada en los destinos.

El vídeo del actor se reproduce hacia delante a velocidad normal. No se invierten los aleteos ni se alarga la escena congelando el último fotograma.
