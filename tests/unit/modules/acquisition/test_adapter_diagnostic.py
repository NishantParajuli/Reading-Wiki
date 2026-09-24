from types import SimpleNamespace

import pytest

import try_adapter
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ChapterData, PremiumReached


class Session:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.parametrize("maximum", ["0", "-1", "1.5"])
def test_diagnostic_rejects_invalid_limits(maximum):
    with pytest.raises(SystemExit) as exc:
        try_adapter.main(["readhive", "https://readhive.org/series/1/1/", "--max", maximum])
    assert exc.value.code == 2


def test_diagnostic_uses_safe_context_and_prints_no_prose(monkeypatch, capsys):
    seen = []

    async def crawl(context):
        seen.append(context)
        for number in range(1, 4):
            yield ChapterData(number, f"Chapter {number}", "Private sample chapter prose.")

    monkeypatch.setattr(try_adapter, "AsyncSession", Session)
    monkeypatch.setattr(try_adapter, "get_adapter", lambda name: SimpleNamespace(
        allowed_hosts=["api.example.com"], crawl=crawl))
    monkeypatch.setattr(try_adapter.settings, "SCRAPER_ALLOWED_HOST_OVERRIDES", "images.example.com")
    monkeypatch.setattr(try_adapter.settings, "SCRAPER_DELAY", 0)
    monkeypatch.setenv("TEST_ARCHIVE_PASSWORD", "test-secret")
    assert try_adapter.main(["readhive", "https://readhive.org/series/1/1/",
                             "--archive-password-env", "TEST_ARCHIVE_PASSWORD"]) == 0
    output = capsys.readouterr()
    assert "Checked 2 chapter(s). Nothing was saved." in output.out
    assert "Private sample" not in output.out
    assert "test-secret" not in output.out + output.err
    assert seen[0].max_chapters == 2
    assert seen[0].source_host == "readhive.org"
    assert seen[0].allowed_hosts == {"api.example.com", "images.example.com"}
    assert seen[0].require_same_host == try_adapter.settings.SCRAPER_REQUIRE_SAME_HOST
    assert seen[0].config == {"archive_password": "test-secret"}


def test_diagnostic_redacts_password_from_failure(monkeypatch, capsys):
    async def fail(*args):
        raise ValueError("Could not decrypt using test-secret")

    monkeypatch.setenv("TEST_ARCHIVE_PASSWORD", "test-secret")
    monkeypatch.setattr(try_adapter, "probe", fail)
    assert try_adapter.main(["raw-fucknovelpia", "https://raw-fucknovelpia.com/novel/sample",
                             "--archive-password-env", "TEST_ARCHIVE_PASSWORD"]) == 1
    error = capsys.readouterr().err
    assert "Check failed:" in error
    assert "test-secret" not in error
    assert "[redacted]" in error


def test_diagnostic_missing_password_is_configuration_failure(monkeypatch, capsys):
    monkeypatch.delenv("TEST_ARCHIVE_PASSWORD", raising=False)
    assert try_adapter.main(["readhive", "https://readhive.org/series/1/1/",
                             "--archive-password-env", "TEST_ARCHIVE_PASSWORD"]) == 2
    assert "missing or empty" in capsys.readouterr().err


@pytest.mark.parametrize("locked,expected", [(True, 0), (False, 1)])
def test_diagnostic_distinguishes_locked_boundary_from_empty_result(monkeypatch, capsys, locked, expected):
    async def crawl(context):
        if locked:
            raise PremiumReached(3, "Locked title")
        if False:
            yield

    monkeypatch.setattr(try_adapter, "AsyncSession", Session)
    monkeypatch.setattr(try_adapter, "get_adapter", lambda name: SimpleNamespace(allowed_hosts=[], crawl=crawl))
    assert try_adapter.main(["readhive", "https://readhive.org/series/1/1/"]) == expected
    output = capsys.readouterr()
    assert ("Premium/locked boundary" in output.out) == locked
    assert ("No chapters were found" in output.err) != locked
