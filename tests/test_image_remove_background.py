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


def test_screen_uses_shared_keyer(tmp_path):
    image=Image.new('RGB',(100,100),(0,255,0));ImageDraw.Draw(image).rectangle((30,30,69,79),fill='red');image.save(tmp_path/'source.png')
    args={'version':1,'intent_id':'screen','input':{'workspace':'test','source':str(tmp_path/'source.png'),'crop':True}}
    result=execute(args,lambda ws:str(tmp_path),str(tmp_path/'uploads'))['result']
    assert result['method']=='screen'
    assert result['bbox']==[28,28,72,82]
    assert np.asarray(Image.open(tmp_path/result['file']))[0,0,3]==0
