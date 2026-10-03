"""The shared downloader refuses anything outside its policy before or while reading."""
import hashlib
import io
import urllib.request

import pytest

from services import secure_download as sd


@pytest.mark.parametrize("url,code", [
    ("http://github.com/a.zip", "not_https"),
    ("ftp://github.com/a.zip", "not_https"),
    ("https://evil.example/a.zip", "host_not_allowed"),
    ("https://user:secret@github.com/a.zip", "credentials"),
    ("https://token@github.com/a.zip", "credentials"),
    ("", "not_https"),
])
def test_urls_outside_the_policy_are_refused(url, code):
    with pytest.raises(sd.DownloadRefused) as caught:
        sd.check_url(url, ["github.com"])
    assert caught.value.code == code


def test_allowed_url_passes_and_hosts_ignore_case():
    assert sd.check_url("https://GitHub.com/a.zip", ["github.com"]) == "https://GitHub.com/a.zip"


def _redirect(target, hosts=("github.com", "objects.githubusercontent.com")):
    handler = sd._AllowedRedirects(frozenset(hosts))
    request = urllib.request.Request("https://github.com/owner/repo/releases/download/v1/a.zip")
    return handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, target)


def test_redirects_only_go_to_allowed_https_hosts():
    assert _redirect("https://objects.githubusercontent.com/a.zip").full_url == "https://objects.githubusercontent.com/a.zip"
    assert _redirect("/owner/other.zip").full_url == "https://github.com/owner/other.zip"
    for target in ("https://evil.example/a.zip", "http://objects.githubusercontent.com/a.zip",
                   "https://x:y@objects.githubusercontent.com/a.zip"):
        with pytest.raises(sd.DownloadRefused) as caught:
            _redirect(target)
        assert caught.value.code == "redirect_refused"


def test_open_url_checks_first_and_installs_only_the_guarded_redirect_handler(monkeypatch):
    captured = {}

    class Opener:
        def open(self, request, timeout):
            captured.update(url=request.full_url, timeout=timeout, agent=request.get_header("User-agent"))
            return io.BytesIO(b"ok")

    def build_opener(*handlers):
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(sd.urllib.request, "build_opener", build_opener)
    with pytest.raises(sd.DownloadRefused):
        sd.open_url("https://evil.example/x", hosts=["github.com"])
    assert "handlers" not in captured
    assert sd.opener_for(["github.com"], "Test/1")("https://github.com/x", 7).read() == b"ok"
    assert captured["url"] == "https://github.com/x" and captured["timeout"] == 7 and captured["agent"] == "Test/1"
    assert [type(handler) for handler in captured["handlers"]] == [sd._AllowedRedirects]


def test_reads_are_bounded():
    assert sd.read_limited(io.BytesIO(b"x" * 10), 10) == b"x" * 10
    with pytest.raises(sd.DownloadRefused) as caught:
        sd.read_limited(io.BytesIO(b"x" * 11), 10)
    assert caught.value.code == "too_large"
    opened = []
    data = sd.fetch_limited("https://github.com/i.json", 5, hosts=["github.com"],
                            opener=lambda url, timeout: opened.append(url) or io.BytesIO(b"{}"))
    assert data == b"{}" and opened == ["https://github.com/i.json"]
    with pytest.raises(sd.DownloadRefused):
        sd.fetch_limited("https://evil.example/i.json", 5, hosts=["github.com"],
                         opener=lambda url, timeout: pytest.fail("must check the host first"))


def _copy(payload, size=None, sha=None, cancelled=lambda: False):
    output, seen = io.BytesIO(), []
    sd.copy_verified(io.BytesIO(payload), output, size=len(payload) if size is None else size,
                     sha256=hashlib.sha256(payload).hexdigest() if sha is None else sha,
                     cancelled=cancelled, progress=seen.append)
    return output.getvalue(), seen


def test_streamed_copy_needs_exact_size_and_checksum():
    payload = b"abc" * 1000
    assert _copy(payload) == (payload, [len(payload)])
    for kwargs, code in (({"size": 10}, "too_large"), ({"size": len(payload) + 1}, "integrity"),
                         ({"sha": "0" * 64}, "integrity"), ({"sha": ""}, "checksum_missing")):
        with pytest.raises(sd.DownloadRefused) as caught:
            _copy(payload, **kwargs)
        assert caught.value.code == code
    with pytest.raises(sd.DownloadCancelled):
        _copy(payload, cancelled=lambda: True)


def test_verify_bytes():
    assert sd.verify_bytes(b"x", hashlib.sha256(b"x").hexdigest()) == b"x"
    with pytest.raises(sd.DownloadRefused):
        sd.verify_bytes(b"x", "0" * 64)


def test_existing_callers_use_the_shared_policy():
    from services import example_collections, template_community

    with pytest.raises(sd.DownloadRefused):
        example_collections.urlopen("https://example.invalid/demo.zip", timeout=1)
    from services.template_format import TemplateError

    with pytest.raises(TemplateError) as caught:
        template_community.http_fetch("http://ianmove.github.io/index.json", 10)
    assert caught.value.code == "not_https"
