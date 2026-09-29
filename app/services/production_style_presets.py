"""Named looks expanded from productions that already rendered.

``anime`` is the promo musical style. ``riso-zine`` is Love the Machine
(omarchy-riso-20260929/love-the-machine.production.json). ``omarchy-desktop``
is keyboard-first (omarchy-tokyo-night-20260929). ``neo-noir-realista`` is
City of Windows (omarchy-neon-20260929/city-of-windows.production.json).
"""
from __future__ import annotations

import copy
import json
from typing import Any

UNKNOWN_PRESET = "unknown_style_preset"
PRESET_IDS = ("anime", "riso-zine", "omarchy-desktop", "neo-noir-realista")
PRESETS: dict[str, dict] = json.loads(r"""
{
  "anime": {
    "image": "Cinematic anime key frame, rich painterly lighting, clean lineart, 16:9.",
    "video": "Cinematic anime animation with rich painterly lighting and clean lineart.",
    "lyric_template": "social-caption",
    "finish": {
      "finish": {
        "grade": {
          "exposure": 0.05,
          "contrast": 0.12,
          "saturation": 0.1,
          "temperature": 0.2,
          "tint": 0.04,
          "fade": 0.05
        },
        "vignette": {
          "amount": 0.3,
          "softness": 0.6
        }
      }
    }
  },
  "riso-zine": {
    "image": "Wide 16:9 cyberpunk paper zine, bold flat risograph spot inks in persimmon orange, electric pink, cobalt blue and near-black on warm paper, coarse halftone grain, tiny offset registration, torn paper collage, punchy editorial composition, hand-cut shapes, expressive caricature, zero anime, zero photorealism, no embedded words or letters.",
    "video": "Cyberpunk paper zine motion, flat risograph ink, halftone texture, paper fibers and offset registration. Handmade cutout movement and snappy editorial rhythm. No realistic lip movement for DHH; only the fictional narrator sings.",
    "image_model": "qwen_image_21",
    "image_steps": 40,
    "lyric_template": "dymo",
    "footer": "Fan-made parody, not affiliated with DHH, 37signals or Omarchy",
    "footer_style": {
      "color": "#F4EEE2",
      "box": {
        "kind": "solid",
        "color": "#1B1718",
        "opacity": 0.95,
        "padding": 0.25
      }
    },
    "finish": {
      "preset": "risoPress"
    },
    "lyric_style": {
      "y": 86,
      "size": 3.3,
      "maxWidth": 82,
      "rotation": 0,
      "color": "#1B1718",
      "box": {
        "kind": "tape",
        "color": "#F4EEE2",
        "opacity": 1,
        "padding": 0.72,
        "radius": 0.18
      },
      "trap": true
    }
  },
  "omarchy-desktop": {
    "image": "Authentic dark Omarchy Hyprland Tokyo Night desktop; native tiling windows, terminal, neovim, btop, slim top bar, exact monospace interface geometry, no illustration or anime.",
    "video": "Native Omarchy desktop motion: precise window openings, focus changes and workspace slides on musical beats. No on-screen singer; the lyric is kinetic typography.",
    "theme": "tokyo-night",
    "lyric_template": "social-caption",
    "lyric_style": {
      "font": "mono",
      "size": 3.5,
      "y": 86,
      "maxWidth": 86,
      "color": "#C0CAF5",
      "box": {
        "kind": "solid",
        "color": "#1A1B26",
        "opacity": 0.96,
        "padding": 0.48
      }
    },
    "title_style": {
      "font": "mono",
      "color": "#C0CAF5"
    },
    "finish": {
      "finish": {
        "grade": {
          "contrast": 0.06,
          "saturation": 0.02,
          "temperature": -0.1
        }
      }
    }
  },
  "neo-noir-realista": {
    "image": "Wide cinematic 16:9 futuristic neo-noir night city in heavy rain, beautiful rain-slick streets, monumental dark architecture, cyan and electric magenta signage glow without readable words, amber haze, distant flying transit, deep shadows, reflective glass, realistic photographic composition, dramatic atmosphere, crisp detail, no anime, no logos, no copied film characters.",
    "video": "Cinematic futuristic neo-noir in a rain-soaked megacity, slow controlled camera motion, cyan and magenta reflections, amber haze, deep navy shadows, realistic photography, precise cuts on the beat. The visuals tell a story of finding an elegant keyboard-first Omarchy desktop; no one sings on screen and no mouth moves with the song.",
    "image_model": "flux2_klein_9b",
    "image_steps": 4,
    "lyric_template": "social-caption",
    "lyric_style": {
      "y": 88,
      "size": 3.4,
      "font": "mono",
      "color": "#E9F2FF",
      "maxWidth": 84,
      "box": {
        "kind": "solid",
        "color": "#111927",
        "opacity": 0.9,
        "padding": 0.35
      }
    },
    "title_style": {
      "font": "mono",
      "color": "#E9F2FF"
    },
    "footer": "Fan-made, not affiliated with Omarchy",
    "footer_style": {
      "color": "#E9F2FF",
      "box": {
        "kind": "solid",
        "color": "#111927",
        "opacity": 0.85,
        "padding": 0.25
      }
    },
    "finish": {
      "finish": {
        "grade": {
          "contrast": 0.18,
          "saturation": 0.05,
          "temperature": -0.22
        },
        "vignette": {
          "amount": 0.22,
          "softness": 0.7
        },
        "bloom": {
          "amount": 0.15,
          "threshold": 0.75,
          "radius": 0.35
        }
      }
    }
  }
}
""")


def expand_style_preset(spec: Any) -> Any:
    """Fill style from a preset. Keys set beside the preset replace those fields."""
    if not isinstance(spec, dict):
        return spec
    style = spec.get("style")
    if not isinstance(style, dict) or "preset" not in style:
        return spec
    base = _preset_fields(style.get("preset"))
    overlay = {key: value for key, value in style.items() if key != "preset"}
    return {**spec, "style": {**base, **overlay}}


def _preset_fields(name: Any) -> dict:
    if isinstance(name, str) and name in PRESETS:
        return copy.deepcopy(PRESETS[name])
    from services.music_production import ProductionError
    raise ProductionError(UNKNOWN_PRESET, f"unknown style preset {name}")
