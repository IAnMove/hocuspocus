"""The words a Video 3D template search understands in either language.

A card carries short English and Spanish copy plus the derived trait words (``shot``, ``moves``, ``uses``...).
People and language models ask in their own words: «diálogo tenso», «plano general», «persecución», «que se mueva».
Each group below is one meaning; a query word is matched against every word of its group, so «diálogo» finds the
cards whose ``uses`` say ``dialogue`` and «girar alrededor» finds the orbits. A word belongs to one group only
(``test_world3d_template_traits`` checks it), and the literal word always outranks a synonym in the scoring.
"""
from __future__ import annotations

SHOT_SIZES = ("close", "medium", "wide", "far", "plate")
USES = ("dialogue", "talk", "reaction", "figure", "establishing", "action", "reveal", "product", "music", "drive",
        "transition", "title", "look", "plate")
MOVES = ("push", "pull", "slide", "rise", "descend", "arc", "orbit", "zoom", "roll", "ride", "track", "shake")
MOVING = ("camera", "subjects", "props", "screens", "effects", "backdrop", "texts")
FORMATS = ("landscape", "portrait")

# Words that name the thing being searched rather than what it shows; dropped from a query unless nothing else is left.
QUERY_STOP = frozenset((
    "a al ante con de del e el en la las lo los o para por que se sin su sus u un una unas unos y "
    "an and as at by for from in into of on or the to with "
    "plano planos toma tomas shot shots camara camera escena escenas scene scenes plantilla plantillas template "
    "templates video videos clip"
).split())

GROUPS: tuple[frozenset[str], ...] = tuple(frozenset(words.split()) for words in (
    # what the shot is for
    "dialogue dialogo dialogos dialog conversacion conversation charla chat hablan discuten discusion argument two dos "
    "pair pareja duo couple ambos both encuentro encounter careo confrontacion confrontation",
    "talk talking hablar habla hablando speech speak speaking monologo monologue voz voice narrador narrator "
    "narracion narration presentador presenter presenta entrevista interview lipsync boca mouth canta sing singing cantar",
    "reaction reaccion reacciona mirada gaze rostro face cara closeup close primer primerisimo cerca cercano intimo "
    "intimate retrato portrait ojos eyes expresion expression busto bust",
    "medium medio cintura waist torso mitad",
    "figure figura wide general amplio amplia abierto abierta entero entera full cuerpo body completo completa whole",
    "establishing establecimiento lugar place sitio location localizacion paisaje landscape panoramica panorama "
    "panoramic exterior far lejos lejano lejana distancia distant vista view entorno mundo world",
    "action accion pelea fight fighting lucha combate combat duelo duel golpe hit punch impacto impact persecucion "
    "chase chasing pursuit huida escape carrera run running correr salto jump batalla battle ataque attack disparo "
    "shoot shooting explosion explosiones estallido blast choque clash intenso intense adrenalina",
    "reveal revelacion revelar revela descubre descubrir grua crane rise rising sube subida ascenso asciende elevacion "
    "eleva descend descends baja bajada desciende descenso picado contrapicado cenital overhead aereo aerial dron drone",
    "product producto productos products objeto object pedestal showcase escaparate anuncio ad advert comercial "
    "commercial marca brand packshot catalogo catalog",
    "music musica musical baile dance dancing bailar baila bailarin dancer cancion song ritmo rhythm beat bpm concierto "
    "concert videoclip coreografia choreography dj banda band",
    "drive driving conducir conduce coche car cars coches vehiculo vehicle vehicles vehiculos carretera road moto "
    "motorcycle bike motorbike tren train nave ship spaceship avion plane aircraft barco boat cockpit cabina hood capo "
    "wing convoy camion truck tunel tunnel ride",
    "transition transicion corte cut eyecatch cortinilla flash flashes destello intersticio interstitial bumper stinger",
    "title titulo titulos titles texto text textos texts rotulo rotulos caption captions subtitulo subtitle letras "
    "lettering tipografia typography cartela card tarjeta creditos credits logo letrero sign",
    "look looks estilo style estetica aesthetic iluminacion lighting luz light lights luces color colour colores colors "
    "lente lens lenses filtro filter grano grain paleta palette tono tone mood atmosfera atmosphere ambiente ambient "
    "viral genre genero cinematografico cinematic film filmico pelicula movie",
    "plate placa fondo fondos background backgrounds backdrop vacio vacia empty nobody nadie deshabitado escenografia "
    "decorado",
    "solo sola alone single individual unico unica only one uno",
    # how the camera moves
    "push pushin acercamiento acercar acerca acercandose aproximacion approach approaching entra entrando dolly dollyin "
    "zoom zoomin zooms tighten tightens cierra closer",
    "pull pullout pullback alejamiento alejar aleja alejandose retrocede retroceso retirada zoomout dollyout widen "
    "widens abre",
    "orbit orbita orbital orbitar girar gira giro alrededor around 360 arc arco circular circulo circle rodea rodear "
    "rodeando vuelta turn turns revolve revolves spin spins rotate rotating rotacion rotation",
    "slide slides lateral deslizar desliza deslizamiento travelling traveling track tracking trucking seguimiento sigue "
    "seguir siguiendo follow follows following paralelo parallel pan panning barrido sweep side sideways costado acompana "
    "acompanar",
    "shake shakes sacudida sacudidas temblor tiembla temblando vibra vibracion vibration handheld mano nervioso nervous "
    "jitter tremble",
    "static estatico estatica fijo fija fixed quieto quieta still inmovil parado parada locked tripod tripode",
    "animated animado animada animacion animation mueve mueva mueven muevan mover moverse moviendo moviendose movimiento "
    "motion moving moves move vivo viva alive dinamico dinamica dynamic",
    "ralenti slow slowmotion slowmo lento lenta despacio suave soft gentle calm calma tranquilo tranquila pausado "
    "pausada sereno serena quiet",
    "fast rapido rapida timelapse acelerado acelerada hyperlapse quick veloz velocidad speed",
    "loop loops bucle bucles seamless repetible repeat repite infinito infinite endless continuo continuous cycle ciclo",
    # what moves and what is in it
    "effects efectos efecto effect fx vfx particulas particles particle polvo dust chispas sparks brasas embers cinders "
    "humo smoke niebla fog bruma mist haze lluvia rain llueve lloviendo raining nieve snow nevada nevando snowing rayo "
    "rayos lightning relampago relampagos tormenta storm thunder trueno fuego fire llamas flames hoguera bonfire splash "
    "salpicadura shockwave onda ondas laser laseres lasers beam haz portal portales portals orb orbe esfera sphere "
    "tornado agujero hole blackhole burst ice hielo glow brillo bloom",
    "model modelo modelos models glb gltf 3d mesh malla rigged riggeado rig humanoid humanoide esqueleto skeleton "
    "hunyuan trellis volumetrico volumetric",
    "cutout cutouts recorte recortes recortable recortables imagen image images imagenes picture pictures foto photo 2d "
    "kit kits png pose poses",
    "subject subjects sujeto sujetos character characters personaje personajes actor actores actors actriz hero heroe "
    "heroina heroine protagonista protagonist lead gente people persona person personas humano human humans chico chica "
    "hombre man mujer woman nino nina child kid",
    "prop props atrezo atrezzo attrezzo utileria item items cosa cosas thing things",
    "screen screens pantalla pantallas monitor monitores monitors tv television televisor televisores crt display "
    "billboard cartelera valla panel paneles panels proyeccion projection hologram holograma",
    # where
    "sea mar oceano ocean olas waves wave playa beach costa coast coastal puerto harbour harbor muelle dock pier cubierta "
    "deck agua water reef arrecife submarino underwater isla islas island islands acantilado cliff cliffs marea tide "
    "fjord fiordo lago lake rio river cascada waterfall pantano marsh swamp piscina pool",
    "city ciudad urban urbano urbana street calle calles streets neon neones azotea rooftop rooftops tejado roof "
    "callejon alley plaza square avenida avenue edificio edificios building buildings skyline metro subway puente bridge "
    "autopista freeway highway rascacielos skyscraper downtown barrio mercado market diner bar cafe cafeteria "
    "restaurante restaurant hotel museo museum tienda shop store gasolinera motel piazza parque park taberna tavern pub "
    "posada inn",
    "space espacio espacial galaxia galaxy galactic estrellas stars star estrella nebulosa nebula asteroide asteroids "
    "asteroid luna moon lunar planeta planet planets marte mars cosmos cosmic cohete rocket launch lanzamiento astronauta "
    "astronaut satelite satellite universo universe void",
    "forest bosque selva jungle arbol arboles tree trees claro clearing pradera meadow prado campo field fields "
    "naturaleza nature montana montanas mountain mountains pico picos peaks valle valley canon canyon cueva cave gruta "
    "grotto volcan volcano volcanic lava desierto desert dunas dunes arena sand hierba grass flores flowers jardin garden "
    "huerto orchard trigo wheat tulipanes tulips koi estanque pond cristal crystal mina mine roca rocks rock piedra stone "
    "ruinas ruins templo temple",
    "night noche nocturno nocturna dark oscuro oscura sombrio sombria gloomy midnight medianoche tenebroso tenebrosa "
    "shadow shadows sombra sombras penumbra moonlit moonlight",
    "day dia daylight sol sun sunny soleado soleada amanecer dawn sunrise atardecer sunset dusk crepusculo twilight "
    "golden dorado dorada tarde afternoon manana morning mediodia noon verano summer primavera spring otono autumn fall "
    "invierno winter estacion estaciones season seasons clima weather",
    "stage escenario escenarios teatro theatre theater plato tarima podium podio pista pasarela runway catwalk alfombra "
    "carpet gala show espectaculo performance performer",
    "room rooms habitacion habitaciones sala salas interior interiores indoor indoors cuarto oficina office despacho "
    "taller workshop laboratorio lab laboratory casa house hogar home dormitorio bedroom cocina kitchen salon lounge "
    "pasillo corridor hallway garaje garage hangar almacen warehouse fabrica factory hospital aula classroom escuela "
    "school iglesia church catedral cathedral palacio palace mansion prision prison carcel jail banco bank boveda vault "
    "casino biblioteca library archivo archive servidor servers server mainframe ordenador computer computers "
    "escritorio desk mesa table ventana window puerta door ascensor elevator escalera stairs stairway torre tower reloj "
    "clock",
    # looks and families
    "pixel pixels pixelart 8bit 16bit retro psx ps1 playstation lowpoly n64 voxel voxels arcade videojuego videojuegos "
    "videogame videogames game games juego juegos consola console sprite sprites pixelado pixelada pixelated dither "
    "synthwave vaporwave outrun retrowave 80s 90s",
    "anime manga shonen otaku toon cartoon cel celshading cels dibujos dibujo comic comics tebeo caricatura caricature "
    "aura",
    "fantasy fantasia fantastico fantastica medieval dragon dragones dragons caballero knight knights castillo castle "
    "castles magia magic magical magico magica hechizo spell spells mago maga wizard witch bruja brujo gotico gothic "
    "terror horror miedo fear monstruo monster monsters demonio demon demons criatura creature creatures titan titanes "
    "espada sword swords armadura armor armour trono throne rey king reina queen reino kingdom oraculo oracle santo "
    "saint peregrino pilgrim campana bell cripta crypt tumba grave tomb cementerio cemetery invocacion summoning ritual "
    "altar",
    "creative creativo creativa ilustracion illustration ilustrado ilustrada illustrated papel paper collage poster "
    "cartel flat editorial grafico grafica graphic diseno design artistico artistica artistic pintado pintada painted "
    "pintura painting acuarela watercolor tinta ink boceto sketch",
    "perspective perspectiva capas layers layered parallax paralaje profundidad depth diorama dioramas topdown "
    "isometrico isometric",
    "formatportrait vertical movil mobile reels reel tiktok shorts stories story 9x16",
    "formatlandscape horizontal apaisado apaisada widescreen 16x9 youtube",
))

_GROUP_OF: dict[str, frozenset[str]] = {}
for _group in GROUPS:
    for _word in _group:
        _GROUP_OF.setdefault(_word, _group)


def expand(token: str) -> frozenset[str]:
    """Every word that means the same as ``token``, the token itself included."""
    return _GROUP_OF.get(token, frozenset({token}))


def duplicated_words() -> set[str]:
    """Words listed in more than one group (meant to be empty)."""
    seen: set[str] = set()
    twice: set[str] = set()
    for group in GROUPS:
        twice |= seen & group
        seen |= group
    return twice
