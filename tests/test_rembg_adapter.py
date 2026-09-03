from types import SimpleNamespace

from PIL import Image

from services import rembg_adapter


def _capture_remove(monkeypatch):
    captured = {}

    def fake_remove(image, **kwargs):
        captured["image"] = image
        captured["kwargs"] = kwargs
        return image

    monkeypatch.setitem(
        __import__("sys").modules,
        "rembg",
        SimpleNamespace(remove=fake_remove, new_session=lambda *_args, **_kwargs: "session"),
    )
    rembg_adapter.clear_session_cache()
    return captured


def test_default_cutout_uses_white_transparent_bgcolor(monkeypatch):
    captured = _capture_remove(monkeypatch)
    image = Image.new("RGBA", (4, 4), (40, 80, 180, 255))

    result = rembg_adapter.remove_background_image(image, session="injected")

    assert result.mode == "RGBA"
    assert captured["kwargs"]["session"] == "injected"
    assert captured["kwargs"]["alpha_matting"] is True
    assert captured["kwargs"]["bgcolor"] == [255, 255, 255, 0]


def test_none_bgcolor_skips_white_composite(monkeypatch):
    captured = _capture_remove(monkeypatch)
    image = Image.new("RGBA", (4, 4), (180, 80, 40, 255))

    rembg_adapter.remove_background_image(
        image, session="injected", alpha_matting=False, bgcolor=None,
    )

    assert "bgcolor" not in captured["kwargs"]
    assert captured["kwargs"]["alpha_matting"] is False


def test_white_transparent_bgcolor_leaves_a_white_halo_on_clear_pixels():
    # rembg.apply_background_color composites over the requested bgcolor.
    # Fully transparent edge pixels then become white-with-zero-alpha, which
    # bilinear overlay sampling reads as a halo.
    cutout = Image.new("RGBA", (2, 1))
    cutout.putpixel((0, 0), (180, 80, 40, 128))
    cutout.putpixel((1, 0), (180, 80, 40, 0))

    with_white = Image.alpha_composite(
        Image.new("RGBA", cutout.size, (255, 255, 255, 0)),
        cutout,
    )

    assert with_white.getpixel((1, 0)) == (255, 255, 255, 0)
    assert cutout.getpixel((1, 0)) == (180, 80, 40, 0)
