#!/usr/bin/env python3
"""More claymation movie parodies with kinder or silly endings."""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("MAESTRO_API", "http://127.0.0.1:42004")
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overnight_surprise import (  # noqa: E402
    API,
    CARTOON,
    CLAY,
    CLAY_CUTE,
    CLAY_NOIR,
    CLAY_POP,
    generate_sequence,
    log,
    wait_idle,
)

PAPA = [
    {
        "label": "despacho",
        "seconds": 10,
        "visual": (
            "The Godfather, claymation 1940s office, Don Corleone in a tuxedo behind a desk, "
            "cat on his lap, blinds, fingerprints on the plasticine suit."
        ),
        "line": "Le haré una oferta que no podrá rechazar.",
    },
    {
        "label": "oferta",
        "seconds": 8,
        "visual": (
            "Changed ending: the Don slides a box of cannoli across the desk instead of a threat. "
            "The visitor unwraps one. The cat licks sugar."
        ),
        "line": "Son de ricotta. Siéntese.",
    },
    {
        "label": "mesa",
        "seconds": 10,
        "visual": (
            "Family dinner, long table, claymation, everyone eating cannoli and grapes. "
            "No horse, no gun. A wedding in the garden behind the window."
        ),
    },
    {
        "label": "brindis",
        "seconds": 8,
        "visual": (
            "The Don raises a tiny glass. Michael smiles. They toast. "
            "A bakery sign outside: Corleone Cannoli."
        ),
        "line": "La familia es la receta.",
    },
]

TIBURON = [
    {
        "label": "boya",
        "seconds": 10,
        "visual": (
            "Jaws, claymation Amity beach, a yellow barrel on the water, Brody on the Orca, "
            "Spielberg 1975, grey sea, plasticine shark fin."
        ),
    },
    {
        "label": "aparece",
        "seconds": 10,
        "visual": (
            "The great white clay shark rises beside the boat, huge teeth. Quint and Hooper freeze. "
            "Then the shark sniffs a bucket of fish."
        ),
        "line": "¿Tienes hambre, grandullón?",
    },
    {
        "label": "pesca",
        "seconds": 8,
        "visual": (
            "Changed ending: they throw it a whole clay tuna. The shark eats politely. "
            "No explosion. Brody sits down."
        ),
    },
    {
        "label": "playa",
        "seconds": 10,
        "visual": (
            "Amity beach reopened. Families swim. The shark floats offshore like a lifeguard. "
            "A sign: Tiburón amigo."
        ),
        "line": "Podemos volver al agua.",
    },
]

ROCKY = [
    {
        "label": "escaleras",
        "seconds": 10,
        "visual": (
            "Rocky, claymation Philadelphia, grey hoodie, running up the Art Museum steps, "
            "dawn, breath in the cold, fingerprints on the gloves."
        ),
    },
    {
        "label": "alto",
        "seconds": 8,
        "visual": (
            "Rocky at the top, arms up, city behind him. Then Adrian arrives with a pizza box."
        ),
        "line": "Adrian… ¿has traído extra de queso?",
    },
    {
        "label": "pizza",
        "seconds": 10,
        "visual": (
            "Changed ending: Rocky and Apollo share the pizza on the steps instead of fighting. "
            "Kids sit around. No blood. Morning light."
        ),
    },
    {
        "label": "baile",
        "seconds": 8,
        "visual": (
            "They dance badly on the steps. A clay crowd claps. "
            "A banner: Campeones de la pizza."
        ),
        "line": "Yo no peleo con el estómago lleno.",
    },
]

FUTURO = [
    {
        "label": "delorean",
        "seconds": 10,
        "visual": (
            "Back to the Future, claymation DeLorean in a mall parking lot, 1985, "
            "Doc with wild hair, Marty with a guitar, tyre tracks of fire as a visual glow only."
        ),
    },
    {
        "label": "1955",
        "seconds": 8,
        "visual": (
            "Hill Valley 1955 town square, clock tower. Marty in a clay waistcoat. "
            "The DeLorean is parked at a diner."
        ),
        "line": "Doc, el desayuno es mejor aquí.",
    },
    {
        "label": "diner",
        "seconds": 10,
        "visual": (
            "Changed ending: Marty, Doc and young George McFly eat pancakes. "
            "They do not rush the lightning. The clock is just a clock."
        ),
    },
    {
        "label": "casa",
        "seconds": 8,
        "visual": (
            "They stay in 1955 for a porch evening. The DeLorean has a 'cerrado por vacaciones' sign. "
            "No paradox, just lemonade."
        ),
        "line": "El futuro puede esperar.",
    },
]

CAZAFANTASMAS = [
    {
        "label": "manhattan",
        "seconds": 10,
        "visual": (
            "Ghostbusters, claymation 1984 New York, Stay Puft Marshmallow Man towering over streets, "
            "the Ecto-1 tiny below, fingerprints on white foam."
        ),
    },
    {
        "label": "cruza",
        "seconds": 8,
        "visual": (
            "Stay Puft waves. Venkman looks up. No proton streams as weapons: they pull out sticks."
        ),
        "line": "¿Alguien tiene chocolate?",
    },
    {
        "label": "hoguera",
        "seconds": 10,
        "visual": (
            "Changed ending: the Ghostbusters roast marshmallows from Stay Puft's friendly hand. "
            "Kids on a rooftop. City lights."
        ),
    },
    {
        "label": "tienda",
        "seconds": 8,
        "visual": (
            "A marshmallow stall opens in Central Park. Stay Puft sits like a mascot. "
            "The ghost trap is a cookie jar."
        ),
        "line": "Negocio redondo.",
    },
]

DURO = [
    {
        "label": "nakatomi",
        "seconds": 10,
        "visual": (
            "Die Hard, claymation Nakatomi Plaza at night, John McClane in a tank top, "
            "bare feet, Christmas tree in the lobby, 1988 action still as plasticine."
        ),
    },
    {
        "label": "frase",
        "seconds": 8,
        "visual": (
            "McClane faces Hans, smiling, holding a clay soda can instead of a gun."
        ),
        "line": "Yippee-ki-yay. ¿Un refresco?",
    },
    {
        "label": "fiesta",
        "seconds": 10,
        "visual": (
            "Changed ending: the hostages come out, everyone has cake. "
            "Hans sits down and takes a slice. No explosion."
        ),
    },
    {
        "label": "tejado",
        "seconds": 8,
        "visual": (
            "Holly and John on the roof, snow, city. Argyle honks the limo. "
            "A banner: Fiesta de Navidad, no villanos."
        ),
        "line": "Este año sí hay vacaciones.",
    },
]

IMPERIO = [
    {
        "label": "pasarela",
        "seconds": 10,
        "visual": (
            "The Empire Strikes Back, claymation Cloud City walkway, Luke and Vader, "
            "red and blue sabers as glowing clay rods, wind, fingerprints."
        ),
    },
    {
        "label": "padre",
        "seconds": 8,
        "visual": (
            "Vader lowers the saber. Close on the mask."
        ),
        "line": "Yo soy tu padre. Y los domingos hago gofres.",
    },
    {
        "label": "gofres",
        "seconds": 10,
        "visual": (
            "Changed ending: they sit at a Cloud City cafe. Vader's helmet is on the chair. "
            "A stack of waffles. Luke laughs."
        ),
    },
    {
        "label": "familia",
        "seconds": 8,
        "visual": (
            "Leia and Han arrive. The whole family at the table. No carbonite. "
            "The city floats in sunset clay."
        ),
        "line": "El lado luminoso huele a sirope.",
    },
]

FORREST = [
    {
        "label": "banco",
        "seconds": 10,
        "visual": (
            "Forrest Gump, claymation Savannah bench, box of chocolates, "
            "white suit, bus stop, pigeons of plasticine."
        ),
        "line": "La vida es como una caja de bombones.",
    },
    {
        "label": "abre",
        "seconds": 8,
        "visual": (
            "He opens the box with both hands and offers chocolates down the bench. "
            "Jenny sits beside him. Closed lips. Pigeons hop. He keeps handing pieces out."
        ),
    },
    {
        "label": "parque",
        "seconds": 10,
        "visual": (
            "Changed ending: Forrest, Jenny and little Forrest picnic on the grass. "
            "They unpack the basket, fly a kite, pass sandwiches. Closed lips. No running away."
        ),
    },
    {
        "label": "casa",
        "seconds": 8,
        "visual": (
            "The Gump house, porch, lemonade. Forrest rocks. Jenny reads. "
            "The chocolates are empty and everyone is happy."
        ),
        "line": "Este me gusta. Es de fresa.",
    },
]

SOLO_EN_CASA = [
    {
        "label": "casa",
        "seconds": 10,
        "visual": (
            "Home Alone, claymation suburban house at Christmas, Kevin in a sweater walks "
            "the hallway setting toy-car traps, two burglars in black knit caps peek in. "
            "Closed lips. Lights blink. He keeps moving."
        ),
    },
    {
        "label": "trampa",
        "seconds": 8,
        "visual": (
            "The burglars slip on toy cars. Kevin watches. Then he holds out cookies."
        ),
        "line": "¿Queréis leche también?",
    },
    {
        "label": "galletas",
        "seconds": 10,
        "visual": (
            "Changed ending: Kevin, Harry and Marv eat cookies at the kitchen table. "
            "They pass the plate, pour milk, paint cans hang unused. Closed lips. Christmas lights."
        ),
    },
    {
        "label": "arbol",
        "seconds": 8,
        "visual": (
            "The family returns. Everyone around the tree. The burglars have ugly sweaters. "
            "Kevin smiles."
        ),
        "line": "Esta casa es para fiestas, no para guerras.",
    },
]

GLADIADOR = [
    {
        "label": "arena",
        "seconds": 10,
        "visual": (
            "Gladiator, claymation Colosseum, Maximus in armor walks the sand, turns to the stands, "
            "crowd of tiny plasticine people shifting. Closed lips. Ridley Scott gold light."
        ),
    },
    {
        "label": "pregunta",
        "seconds": 8,
        "visual": (
            "Maximus faces the emperor box, arms out."
        ),
        "line": "¿Os estáis divirtiendo?",
    },
    {
        "label": "teatro",
        "seconds": 10,
        "visual": (
            "Changed ending: the gladiators sit in the stands and watch a play. "
            "They lean forward, Commodus claps, sand becomes a stage. Closed lips. No swords."
        ),
    },
    {
        "label": "campo",
        "seconds": 8,
        "visual": (
            "Maximus walks a wheat field toward a farmhouse. His family waits. "
            "Rome is a postcard on the table."
        ),
        "line": "Hoy vuelvo a casa.",
    },
]

PAN = [
    {
        "label": "laberinto",
        "seconds": 10,
        "visual": (
            "Pan's Labyrinth, claymation faun with a carved face leads Ofelia in a green dress "
            "through a stone labyrinth under moonlight. She follows, looking around. Closed lips. "
            "Guillermo del Toro fairy-tale gloom as plasticine."
        ),
    },
    {
        "label": "prueba",
        "seconds": 8,
        "visual": (
            "Ofelia holds a clay key. The faun kneels. No pale man. A banquet of fruit that is safe."
        ),
        "line": "Puedo elegir no tener miedo.",
    },
    {
        "label": "reina",
        "seconds": 10,
        "visual": (
            "Changed ending: Ofelia lives. She sits at the underground court as a living girl, "
            "not a ghost. The faun pours tea, she lifts the cup. Closed lips. Gold light."
        ),
    },
    {
        "label": "jardin",
        "seconds": 8,
        "visual": (
            "Morning above ground: Ofelia in the garden with her mother, smiling. "
            "A small faun statue among the roses."
        ),
        "line": "El cuento sigue, y yo también.",
    },
]

SCARFACE = [
    {
        "label": "despacho",
        "seconds": 10,
        "visual": (
            "Scarface, claymation 1983 Miami mansion, Tony in a white suit walks past gold "
            "and a mountain of money as plasticine bricks, sunset through blinds. Closed lips. "
            "He straightens a stack and keeps walking."
        ),
    },
    {
        "label": "amigo",
        "seconds": 8,
        "visual": (
            "Tony lifts a tiny clay kitten instead of a gun."
        ),
        "line": "Decidle hola a mi pequeño amigo.",
    },
    {
        "label": "gatos",
        "seconds": 10,
        "visual": (
            "Changed ending: the mansion is a cat café. Tony serves milk, guests pet kittens, "
            "he wipes a table. Closed lips. No palace shootout."
        ),
    },
    {
        "label": "terraza",
        "seconds": 8,
        "visual": (
            "Tony on the terrace at dusk, kitten on his shoulder, city lights. "
            "A sign: Little Friend Café."
        ),
        "line": "El mundo es vuestro. El atún también.",
    },
]


def wait_api() -> None:
    for _ in range(90):
        try:
            urllib.request.urlopen(API, timeout=3)
            log(f"parodies2 api up {API}")
            return
        except Exception:
            time.sleep(4)
    raise RuntimeError(f"Maestro not up at {API}")


def main() -> None:
    wait_api()
    wait_idle("parodies2-start")
    films = (
        ("godfather_cannoli", CLAY_NOIR + " The Godfather, cannoli instead of threats.", PAPA),
        ("jaws_amigo", CLAY + " Jaws, the shark becomes a lifeguard.", TIBURON),
        ("rocky_pizza", CLAY_POP + " Rocky shares pizza on the steps.", ROCKY),
        ("bttf_desayuno", CLAY_POP + " Back to the Future, they stay for pancakes.", FUTURO),
        ("ghostbusters_nube", CLAY_CUTE + " Stay Puft marshmallow roast.", CAZAFANTASMAS),
        ("diehard_tarta", CLAY + " Die Hard, Christmas cake not a shootout.", DURO),
        ("vader_gofres", CLAY + " Empire Strikes Back, waffles with Vader.", IMPERIO),
        ("forrest_bombones", CLAY_CUTE + " Forrest Gump shares the chocolates.", FORREST),
        ("homealone_galletas", CLAY_POP + " Home Alone, cookies with the burglars.", SOLO_EN_CASA),
        ("gladiator_casa", CLAY + " Gladiator, he goes home.", GLADIADOR),
        ("pan_vive", CLAY_NOIR + " Pan's Labyrinth, Ofelia lives.", PAN),
        ("scarface_gatos", CLAY_POP + " Scarface, a kitten café.", SCARFACE),
    )
    for name, style, shots in films:
        dest = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs") / f"overnight_{name}_multiclip.mp4"
        if dest.is_file():
            log(f"skip existing {dest.name}")
            continue
        try:
            generate_sequence(name, style, shots)
        except Exception as exc:
            log(f"parody {name} failed: {exc}")
    log("parodies2 done")


if __name__ == "__main__":
    main()
