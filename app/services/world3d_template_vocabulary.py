"""The words a Video 3D template search understands in either language.

A card carries short English and Spanish copy plus the derived trait words (``shot``, ``moves``, ``uses``, ``kind``,
``place``...). People and language models ask in their own words: «diálogo tenso», «plano general», «persecución»,
«que se mueva». Each group below is one meaning; a query word is matched against every word of its group, so
«diálogo» finds the cards whose ``uses`` say ``dialogue`` and «girar alrededor» finds the orbits. A word belongs to
one group only (``test_world3d_template_traits`` checks it), and the literal word always outranks a synonym in the
scoring. Place words are split the way a director tells places apart (a kitchen is not a church), so a stage mold
or a dressing is found by its own words and not by every indoor word at once.
"""
from __future__ import annotations

SHOT_SIZES = ("close", "medium", "wide", "far", "plate")
USES = ("dialogue", "talk", "reaction", "figure", "establishing", "action", "speed", "impact", "reveal", "product",
        "music", "drive", "transition", "title", "look", "plate")
KINDS = ("scene", "stage", "camera", "look", "transition", "title")
MOVES = ("push", "pull", "slide", "rise", "descend", "arc", "orbit", "zoom", "roll", "ride", "track", "shake")
MOVING = ("camera", "subjects", "props", "screens", "effects", "backdrop", "texts")
FORMATS = ("landscape", "portrait")

# Words that name the thing being searched rather than what it shows; dropped from a query unless nothing else is left.
QUERY_STOP = frozenset((
    "a al ante con de del e el en la las lo los o para por que se sin su sus u un una unas unos y sobre hacia desde "
    "no ni es son este esta estos estas ese esa eso "
    "an and as at by for from in into of on or the to with over under through across onto not such this that these those "
    "it its is are be "
    "plano planos toma tomas shot shots camara camera escena escenas scene scenes plantilla plantillas template "
    "templates video videos clip"
).split())

GROUPS: tuple[frozenset[str], ...] = tuple(frozenset(words.split()) for words in (
    # what the shot is for
    "dialogue dialogo dialogos dialog conversacion conversation charla chat hablan discuten discusion argument two dos "
    "pair pareja duo couple ambos both encuentro encounter careo confrontacion confrontation contraplano contraplanos",
    "talk talking talks hablar habla hablando speech speak speaking monologo monologue voz voice voices narrador "
    "narrator narracion narration voiceover off presentador presentadora presenter presenta entrevista interview "
    "lipsync boca mouth canta sing singing cantar cantante singer",
    "reaction reaccion reacciona mirada gaze rostro face cara closeup close primer primerisimo cerca cercano intimo "
    "intimate retrato portrait ojos eyes expresion expression busto bust emocion emotion emociones emotions triste sad "
    "sadness tristeza llora llorar llorando crying cry cries tears lagrimas risa laugh laughing laughs rie riendo smile "
    "sonrisa sorpresa surprise surprised sorprendido asombro shock shocked enfado anger angry enfadado rabia rage furia "
    "fury miedo fear afraid asustado scared panico panic amor love enamorado enamorada grito grita gritando scream "
    "screaming shout shouts shouting smiles mira mirando looking watching observa observing",
    "medium medio cintura waist torso mitad",
    "figure figura wide general amplio amplia abierto abierta entero entera full cuerpo body completo completa whole",
    "establishing establecimiento lugar place sitio location localizacion paisaje landscape panoramica panorama "
    "panoramic exterior exteriores outdoor outdoors far lejos lejano lejana distancia distant vista view entorno mundo "
    "world",
    "action accion pelea fight fighting lucha combate combat duelo duel persecucion chase chasing pursuit huida escape "
    "carrera run runs running correr corre corriendo corren salto jump jumps jumping saltando batalla battle battlefield "
    "guerra war fights "
    "soldado soldier ejercito army "
    "ataque attack disparo shoot shooting gun pistola explosion explosiones estallido blast intenso intense adrenalina",
    "impact impacto impactos golpe golpes hit hits punch punches choque choques clash clashes",
    "reveal revelacion revelar revela descubre descubrir grua crane rise rising sube subida ascenso asciende elevacion "
    "eleva descend descends baja bajada desciende descenso picado contrapicado cenital overhead",
    "aerial aereo aerea aereos aereas dron drone drones fpv flyover sobrevuelo flight vuelo flying fly volar vuela",
    "product producto productos products objeto object pedestal showcase escaparate anuncio ad advert comercial "
    "commercial marca brand packshot catalogo catalog",
    "music musica musical baile dance dancing bailar baila bailarin dancer cancion song ritmo rhythm beat bpm concierto "
    "conciertos concert concerts videoclip coreografia choreography dj banda band bailando bailan dances sings",
    "drive drives driving conducir conduce coche car cars coches vehiculo vehicle vehicles vehiculos carretera road moto "
    "motorcycle bike motorbike tren train nave ship spaceship avion plane aircraft barco boat cockpit cabina hood capo "
    "wing convoy camion truck tunel tunnel ride helicoptero helicopter bus autobus taxi",
    "transition transicion corte cortes cut cuts eyecatch cortinilla flash flashes destello intersticio interstitial "
    "bumper stinger wipe iris",
    "split partida dividida divided mitades halves",
    "title titulo titulos titles texto text textos texts rotulo rotulos caption captions subtitulo subtitle letras "
    "lettering tipografia typography cartela card tarjeta creditos credits logo letrero sign",
    "look looks estilo style estetica aesthetic iluminacion lighting luz light lights luces color colour colores colors "
    "lente lens lenses filtro filter grano grain paleta palette tono tone mood atmosfera atmosphere ambiente ambient "
    "viral genre genero cinematografico cinematic film filmico pelicula movie",
    "plate placa fondo fondos background backgrounds backdrop vacio vacia empty nobody nadie deshabitado escenografia "
    "decorado",
    "solo sola alone single individual unico unica only one uno",
    # how the camera moves
    "push pushin acercamiento acercar acerca acercandose aproximacion approach approaching dolly dollyin zoom zoomin "
    "zooms tighten tightens cierra closer",
    "pull pullout pullback alejamiento alejar aleja alejandose retrocede retroceso retirada zoomout dollyout widen "
    "widens abre",
    "orbit orbita orbital orbitar girar gira giran girando giro alrededor around 360 arc arco circular circulo circle "
    "rodea rodear "
    "rodeando vuelta turn turns revolve revolves spin spins rotate rotating rotacion rotation",
    "slide slides lateral deslizar desliza deslizamiento travelling traveling track tracking trucking seguimiento sigue "
    "seguir siguiendo follow follows following paralelo parallel pan panning barrido sweep side sideways costado acompana "
    "acompanar",
    "shake shakes sacudida sacudidas temblor tiembla temblando vibra vibracion vibration handheld mano nervioso nerviosa "
    "nervous jitter tremble",
    "static estatico estatica fijo fija fixed quieto quieta still inmovil parado parada locked tripod tripode",
    "animated animado animada animacion animation mueve mueva mueven muevan mover moverse moviendo moviendose movimiento "
    "motion moving moves move vivo viva alive dinamico dinamica dynamic",
    "ralenti slow slowmotion slowmo lento lenta despacio suave soft gentle calm calma tranquilo tranquila pausado "
    "pausada sereno serena quiet",
    "fast rapido rapida rapidos rapidas timelapse acelerado acelerada acelera acelerar accelerate accelerates hyperlapse "
    "quick veloz velocidad speed speedy swift",
    "loop loops bucle bucles seamless repetible repeat repite infinito infinite endless continuo continuous cycle ciclo",
    # what the cast does
    "travel walk walks walking camina caminar caminando caminan andar anda andando pasea pasear paseo stroll cruza "
    "cruzar crossing marcha wander wandering pasos",
    "seated sitting sentado sentada sentados sentadas sentarse sienta silla sillas chair chairs",
    "entrance entrances entrada entradas enter enters entering entra entran entrando entrar llega llegan llegando "
    "llegada arrival arrive arrives arriving",
    "crowd crowds multitud multitudes publico audience audiencia espectadores spectators group groups grupo grupos tres "
    "three trio cuatro four cinco five varios several muchos many equipo team cheer cheers cheering aplausos applause "
    "ovacion fans",
    "pov subjetivo subjetiva subjective firstperson",
    "cowboy cowboys americano americana vaquero vaquera",
    "phone phones telefono telefonos llamada llamadas call calls videollamada videollamadas videocall smartphone celular",
    "flashback flashbacks recuerdo recuerdos memoria memory memories sueno suenos dream dreams pesadilla pesadillas "
    "nightmare nightmares onirico onirica dreamy",
    "kiss kisses beso besos besar hug hugs abrazo abrazos abrazar embrace romantic romantico romantica boda wedding "
    "bodas weddings novia bride novio groom",
    # what moves and what is in it
    "effects efectos efecto effect fx vfx particulas particles particle shockwave onda ondas laser laseres lasers beam "
    "haz portal portales portals orb orbe esfera sphere tornado agujero hole blackhole burst glow brillo bloom",
    "humo smoke niebla fog bruma mist haze neblina vapor steam",
    "lluvia rain llueve lloviendo raining tormenta storm thunder trueno rayo rayos lightning relampago relampagos monzon "
    "monsoon",
    "nieve snow nevada nevando snowing ice hielo frost escarcha blizzard ventisca",
    "fuego fire llamas flames hoguera bonfire brasas embers cinders chispas sparks ascuas",
    "polvo dust motas motes",
    "model modelo modelos models glb gltf 3d mesh malla rigged riggeado rigging humanoid humanoide esqueleto skeleton "
    "hunyuan trellis volumetrico volumetric robot robots android androide androids cyborg mecha droide droid",
    "cutout cutouts recorte recortes recortable recortables imagen image images imagenes picture pictures foto photo 2d "
    "kit kits png pose poses",
    "subject subjects sujeto sujetos character characters personaje personajes actor actores actors actriz hero heroe "
    "heroina heroine protagonista protagonist lead gente people persona person personas humano human humans chico chica "
    "hombre man mujer woman nino nina child kid",
    "prop props atrezo atrezzo attrezzo utileria item items cosa cosas thing things",
    "screen screens pantalla pantallas monitor monitores monitors crt display billboard cartelera valla panel paneles "
    "panels proyeccion projection hologram holograma",
    # where: outdoors
    "sea mar oceano ocean olas waves wave playa beach costa coast coastal shore orilla puerto harbour harbor muelle dock "
    "pier cubierta deck agua water reef arrecife submarino underwater isla islas island islands acantilado cliff cliffs "
    "marea tide fjord fiordo faro lighthouse",
    "rio river rivers lago lake lakes cascada waterfall pantano marsh swamp piscina pool estanque pond arroyo stream "
    "laguna lagoon",
    "city ciudad urban urbano urbana street calle calles streets callejon alley plaza square avenida avenue edificio "
    "edificios building buildings skyline metro subway puente bridge autopista freeway highway rascacielos skyscraper "
    "downtown barrio mercado market tienda shop store gasolinera motel hotel piazza neon neones semaforo crosswalk acera "
    "sidewalk trafico traffic",
    "rooftop rooftops azotea azoteas tejado tejados roof roofs terrado cornisa ledge",
    "space espacio espacial galaxia galaxy galactic estrellas stars star estrella nebulosa nebula asteroide asteroids "
    "asteroid luna moon lunar planeta planet planets marte mars cosmos cosmic cohete rocket launch lanzamiento astronauta "
    "astronaut satelite satellite universo universe void",
    "forest bosque selva jungle arbol arboles tree trees claro clearing pradera meadow prado campo field fields "
    "naturaleza nature hierba grass flores flowers jardin garden huerto orchard trigo wheat tulipanes tulips parque park "
    "woods arboleda",
    "montana montanas mountain mountains pico picos peaks valle valley canon canyon cueva cave caves gruta grotto mina "
    "mine roca rocks rock piedra stone cristal crystal cumbre summit sierra alpine alpino glaciar glacier",
    "desert desierto desiertos dunas dunes arena sand oasis espejismo mirage cactus",
    "volcan volcano volcanic volcanes lava magma crater erupcion eruption",
    "night noche nocturno nocturna dark oscuro oscura sombrio sombria gloomy midnight medianoche tenebroso tenebrosa "
    "shadow shadows sombra sombras penumbra moonlit moonlight",
    "day dia daylight sol sun sunny soleado soleada tarde afternoon manana morning mediodia noon",
    "amanecer dawn sunrise alba madrugada",
    "atardecer sunset dusk crepusculo twilight golden dorado dorada ocaso",
    "verano summer primavera spring otono autumn fall invierno winter estacion estaciones season seasons clima weather",
    "stage escenario escenarios teatro theatre theater tarima podium podio pista pasarela runway catwalk alfombra carpet "
    "gala show espectaculo performance performer",
    # where: rooms a director tells apart
    "interior interiores indoor indoors inside dentro room rooms habitacion habitaciones cuarto cuartos estancia sala salas",
    "kitchen kitchens cocina cocinas dining comedor comedores cena dinner cenar lunch almuerzo desayuno breakfast fogon "
    "stove horno oven nevera fridge",
    "mesa mesas table tables mantel tablecloth",
    "bedroom bedrooms dormitorio dormitorios cama camas bed beds alcoba",
    "salon salones lounge sofa couch sillon chimenea fireplace hearth",
    "office offices oficina oficinas despacho despachos desk desks escritorio escritorios cubicle cubiculo reunion "
    "meeting boardroom corporativo corporate empresa company",
    "classroom classrooms aula aulas school schools escuela escuelas colegio instituto university universidad teacher "
    "profesor profesora maestro maestra student students alumno alumnos estudiante estudiantes pizarra blackboard clase "
    "clases lesson leccion lecture filas rows fila row",
    "bar bars cafe cafes cafeteria restaurante restaurant restaurants taberna tavern pub diner bistro cantina terraza "
    "terrace mostrador counter barra camarero waiter bartender",
    "church churches iglesia iglesias cathedral catedral catedrales temple templo templos chapel capilla shrine "
    "santuario altar monastery monasterio abbey abadia mosque mezquita",
    "hospital hospitales clinic clinica clinics doctor doctora medico medica nurse enfermera enfermero quirofano "
    "surgery ward ambulancia ambulance",
    "courtroom courthouse tribunal tribunales juzgado judge juez jury jurado parliament parlamento congress congreso "
    "senate senado hemiciclo trial juicio",
    "studio estudio estudios plato tv television televisor televisores televisiones newsroom press prensa broadcast "
    "news noticias noticiario informativo telediario anchor reportero reporter periodista journalist",
    "door doors puerta puertas doorway umbral threshold stairs stairway staircase escalera escaleras corridor corridors "
    "pasillo pasillos hallway hall window windows ventana ventanas balcony balcon balcones atico attic sotano basement",
    "hangar hangares warehouse almacen factory fabrica lab laboratory laboratorio taller workshop industrial server "
    "servers mainframe ordenador computer computers datacenter reactor refinery refineria plataforma platform cargo "
    "garaje garage",
    "prison prision carcel jail bank banco vault boveda casino library biblioteca museum museo palace palacio mansion "
    "torre tower reloj clock galeria gallery aeropuerto airport embajada embassy",
    # looks and families
    "pixel pixels pixelart 8bit 16bit retro psx ps1 playstation lowpoly n64 voxel voxels arcade videojuego videojuegos "
    "videogame videogames game games juego juegos consola console sprite sprites pixelado pixelada pixelated dither "
    "synthwave vaporwave outrun retrowave 80s 90s",
    "anime manga shonen otaku toon cartoon cel celshading cels dibujos dibujo comic comics tebeo caricatura caricature "
    "aura",
    "fantasy fantasia fantastico fantastica medieval dragon dragones dragons caballero knight knights castillo castle "
    "castles magia magic magical magico magica hechizo spell spells mago maga wizard witch bruja brujo gotico gothic "
    "terror horror monstruo monster monsters demonio demon demons criatura creature creatures titan titanes espada "
    "sword swords armadura armor armour trono throne rey king reina queen reino kingdom oraculo oracle santo saint "
    "peregrino pilgrim campana bell cripta crypt tumba grave tomb cementerio cemetery invocacion summoning ritual "
    "ruinas ruins",
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
