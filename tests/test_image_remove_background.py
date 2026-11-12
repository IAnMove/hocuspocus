import numpy as np
import pytest
from PIL import Image, ImageDraw
from fastapi import HTTPException
from services.image_remove_background import detect_screen, execute, crop_result


def test_auto_detects_screen_borders():
    for color, expected in [((0,255,0),'green'), ((255,0,255),'magenta'), ((0,0,255),'blue'), ((140,140,140),None)]:
        image = Image.new('RGB',(100,100),color)
        ImageDraw.Draw(image).rectangle((30,30,69,79),fill='red')
        assert detect_screen(image)[0] == expected


def test_crop_matches_opaque_bbox():
    image = Image.new('RGBA',(100,100))
    ImageDraw.Draw(image).rectangle((30,30,69,79),fill=(200,0,0,255))
    cropped, box = crop_result(image,True)
    assert box == [28,28,72,82]
    assert cropped.size == (44,54)


def test_auto_uses_worker_and_replays_intent(tmp_path):
    Image.new('RGB',(100,100),'grey').save(tmp_path/'source.png')
    calls = []
    def worker(job):
        calls.append(job)
        image=Image.new('RGBA',(100,100));ImageDraw.Draw(image).rectangle((30,30,69,79),fill='red');image.save(tmp_path/'cut.png')
        job.update(status='completed',output_files=['cut.png'])
    args={'version':1,'intent_id':'test-cut','input':{'workspace':'test','source':str(tmp_path/'source.png'),'crop':True}}
    deps=(lambda ws:str(tmp_path),str(tmp_path/'uploads'),worker)
    first=execute(args,*deps);second=execute(args,*deps)
    assert first['result']==second['result'] and second['replayed']
    assert first['result']['method']=='u2net' and len(calls)==1
    assert first['result']['report']['haze']==0
    args['input']['crop']=False
    with pytest.raises(HTTPException) as exc: execute(args,*deps)
    assert exc.value.status_code==409


def test_auto_skips_a_png_that_is_already_transparent_and_still_segments_rgb(tmp_path):
    """Auto mode must not run U2Net on a cutout. An opaque picture still does."""
    import json
    rgba = Image.new("RGBA", (100, 100), (10, 20, 30, 0))
    ImageDraw.Draw(rgba).rectangle((20, 20, 79, 79), fill=(200, 0, 0, 255))
    rgba.save(tmp_path / "cutout.png")
    Image.new("RGB", (100, 100), "grey").save(tmp_path / "opaque.png")
    Image.new("RGBA", (100, 100), (10, 20, 30, 255)).save(tmp_path / "solid.png")
    mixed = Image.new("RGBA", (100, 100), (0, 255, 0, 255))
    for x in range(10):
        for y in range(10):
            mixed.putpixel((x, y), (0, 0, 0, 0))
    mixed.save(tmp_path / "green-hole.png")
    calls = []

    def worker(job):
        calls.append(job["params"]["source_filename"])
        Image.new("RGBA", (100, 100), (0, 255, 0, 255)).save(tmp_path / "segmented.png")
        job.update(status="completed", output_files=["segmented.png"])

    def run(name, **extra):
        args = {"version": 1, "intent_id": f"cut-{name}-{extra.get('method', 'auto')}",
                "input": {"workspace": "test", "source": str(tmp_path / name), "crop": False, **extra}}
        return execute(args, lambda _ws: str(tmp_path), str(tmp_path / "uploads"), worker)["result"]

    skipped = run("cutout.png")
    assert calls == []
    assert skipped["method"] == "background_already_removed"
    assert skipped["file"] != "cutout.png" and skipped["file"].startswith("cutout.no-background-")
    assert np.array_equal(np.asarray(Image.open(tmp_path / skipped["file"])), np.asarray(rgba))
    meta = json.loads((tmp_path / skipped["file"]).with_suffix(".meta.json").read_text())
    assert "background_already_removed" in json.dumps(meta)
    hole = run("green-hole.png")
    assert calls == [] and hole["method"] == "background_already_removed"
    assert run("opaque.png")["method"] == "u2net" and calls == ["opaque.png"]
    assert run("solid.png")["method"] == "u2net" and calls == ["opaque.png", "solid.png"]
    assert run("cutout.png", method="u2net")["method"] == "u2net" and calls[-1] == "cutout.png"


def test_screen_uses_shared_keyer(tmp_path):
    image=Image.new('RGB',(100,100),(0,255,0));ImageDraw.Draw(image).rectangle((30,30,69,79),fill='red');image.save(tmp_path/'source.png')
    args={'version':1,'intent_id':'screen','input':{'workspace':'test','source':str(tmp_path/'source.png'),'crop':True}}
    result=execute(args,lambda ws:str(tmp_path),str(tmp_path/'uploads'))['result']
    assert result['method']=='screen'
    assert result['bbox']==[28,28,72,82]
    assert np.asarray(Image.open(tmp_path/result['file']))[0,0,3]==0
