import numpy as np
import pytest

from services.phoneme_ctc import align_states, timed_phones, mouth_cues, shapes


def emissions(labels, size=8):
    values = np.full((len(labels), size), -12.)
    values[np.arange(len(labels)), labels] = -.01
    return values


def test_acoustic_vowels_keep_order_and_sustain_across_ctc_blanks():
    logp = emissions([0, 4, 4, 0, 0, 0, 5, 5, 0, 6, 6, 0])
    phones = timed_phones(logp, [4, 5, 6], {4: 'ɔːɹ', 5: 'iː', 6: 'ʌ'}, .02, .0125, .24)
    assert [p['start'] for p in phones] == pytest.approx([.0325, .1325, .1925])
    assert [p['end'] for p in phones] == pytest.approx([.1325, .1925, .24])
    cues = mouth_cues(phones, [], .24)
    assert [c['value'] for c in cues] == ['X', 'E', 'B', 'D']
    # A blank between acoustic spikes must hold the sung vowel, not erase the mouth.
    assert next(c['value'] for c in cues if c['start'] <= .10 < c['end']) == 'E'


def test_repeated_phonemes_must_cross_a_ctc_blank():
    path = align_states(emissions([4, 4, 0, 4, 4, 0]), [4, 4])
    assert np.any(path == 1) and np.any(path == 3)
    assert np.any(path[np.flatnonzero(path == 1)[-1] + 1:np.flatnonzero(path == 3)[0]] == 2)
    with pytest.raises(ValueError, match='cannot fit'):
        align_states(emissions([4, 4]), [4, 4])


def test_real_silence_closes_mouth_without_changing_vowel_timing():
    phones = [{'phoneme': 'ɔ', 'start': .1, 'end': .6}, {'phoneme': 'i', 'start': .6, 'end': 1}]
    cues = mouth_cues(phones, [(.35, .55), (.9, 1)], 1)
    assert [(c['start'], c['end'], c['value']) for c in cues] == [
        (0, .1, 'X'), (.1, .35, 'E'), (.35, .55, 'X'), (.55, .6, 'E'), (.6, .9, 'B'), (.9, 1, 'X')]


@pytest.mark.parametrize('phone,value', [('m', 'A'), ('f', 'G'), ('iː', 'B'), ('ɛ', 'C'), ('ɑː', 'D'), ('ɔːɹ', 'E'), ('ʊ', 'F')])
def test_acoustic_vowels_and_closed_consonants_select_distinct_native_shapes(phone, value):
    assert shapes(phone) == (value,)


def test_diphthong_sustains_then_changes_shape_instead_of_flapping():
    assert mouth_cues([{'phoneme': 'aɪ', 'start': 0, 'end': 1}], [], 1) == [
        {'start': 0, 'end': .75, 'value': 'D'}, {'start': .75, 'end': 1, 'value': 'B'}]
