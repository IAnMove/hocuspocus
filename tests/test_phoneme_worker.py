import sys
from types import SimpleNamespace

from services.phoneme_worker import transcript_tokens


def test_bundled_phonemizer_fork_supplies_ipa_without_transformers_distribution_probe(monkeypatch):
    class Backend:
        def __init__(self, language, **kwargs):
            assert language == 'en-us'
        def phonemize(self, words, **kwargs):
            assert words == ['four', 'more']
            assert kwargs['separator'] == {'phone': ' ', 'word': '|', 'syllable': ''}
            return ['f|ɔːɹ', 'm ɔːɹ']
    monkeypatch.setitem(sys.modules, 'phonemizer.backend', SimpleNamespace(EspeakBackend=Backend))
    monkeypatch.setitem(sys.modules, 'phonemizer.separator', SimpleNamespace(Separator=lambda **kwargs: kwargs))
    received = []
    def tokenizer(ipa, **kwargs):
        received.append(ipa)
        assert kwargs == {'add_special_tokens': False, 'do_phonemize': False}
        return {'input_ids': [23, 71] if ipa.startswith('f') else [13, 71]}
    tokens, words = transcript_tokens(tokenizer, 'four more', 'en-us')
    assert tokens == [23, 71, 13, 71]
    assert words == ['four', 'four', 'more', 'more']
    assert received == ['f ɔːɹ', 'm ɔːɹ']
