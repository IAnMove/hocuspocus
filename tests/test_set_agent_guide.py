"""Discovery contracts an agent receives, without hidden application state."""
from services.series_guide import guide_text, _location
from services.set_commands import command_catalog as molds
from services.prop_commands import command_catalog as props
from services.scene3d_items import command_catalog as items
from services.series_sets import command_catalog as locations
from services.mcp_profiles import SERIES_TOOLS


def test_room_workflow_is_discoverable_in_series_profile():
    guide=guide_text()
    assert '3D sets: molds, skins and props' in guide
    for operation in [*molds(),*props(),*items(),*locations()]:
        assert operation['name'] in SERIES_TOOLS
        assert operation['inputSchema']['properties']['input']['type']=='object'
    for name in ('scene3d.sets.catalog','props.create','props.status','props.approve','scene3d.item.add','scene3d.item.update','scene3d.item.remove'):
        assert name in guide


def test_bible_exposes_room_anchors_and_legacy_locations_stay_identical():
    before={'id':'office','name':'Office','description':None,'variants':[],'hasImage':False}
    assert _location({'id':'office','name':'Office'})==before
    room={'mold':'despacho','size':'medium','skin':{},'props':[]}
    assert _location({'id':'office','set3d':room})['set3d']==room
