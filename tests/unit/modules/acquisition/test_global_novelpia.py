from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from novelwiki.modules.acquisition.adapters.outbound.scraper import global_novelpia as mod
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ScrapeContext, ScrapeError
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import SafeFetchResponse


def ctx(url=mod.SITE + '/novel/4053', maximum=None):
    return ScrapeContext(start_url=url, session=object(), max_chapters=maximum,
                         account_cookies=[{'name': 'TKEY', 'value': 'synthetic-refresh', 'expires': None}])


def metadata(ep=17, number=1, novel=4053):
    return {'data': {'episode_no': ep, 'novel_no': novel, 'epi_num': number,
                     'epi_title': f'Chapter {number}', 'sort_no': 20 + ep, 'flag_content': 0},
            '_t': 'synthetic-chapter-token', 'signed_key': {'CloudFront-Policy': 'never-save'}}


class API:
    def __init__(self, monkeypatch, responses):
        self.responses = responses
        self.calls = []
        monkeypatch.setattr(mod, 'safe_fetch', self.fetch)

    async def fetch(self, session, url, **kwargs):
        p = urlsplit(url)
        assert p.scheme == 'https' and p.hostname == 'api-global.novelpia.com'
        assert kwargs['max_redirects'] == 0 and kwargs['require_same_host']
        assert kwargs['raise_for_status'] is False
        assert kwargs['headers']['Cookie'] == 'TKEY=synthetic-refresh'
        self.calls.append((p.path, parse_qs(p.query), kwargs['headers'].copy()))
        expected, result = self.responses.pop(0)
        assert p.path == '/v1/' + expected
        if isinstance(result, tuple):
            status, payload = result
        else:
            status, payload = 200, {'code': '0000', 'result': result}
        return SafeFetchResponse(url=url, status_code=status, headers={}, body=json.dumps(payload).encode())


async def crawl(context):
    return [c async for c in mod.GlobalNovelpiaAdapter().crawl(context)]


def login():
    return ('login/refresh', {'LOGINAT': 'synthetic-access'})


@pytest.mark.asyncio
async def test_all_parts_preserved_without_tokens_images_author_comments_or_scripts(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode/first', {'episode_no': 17}),
        ('novel/episode', metadata()), ('novel/episode/content', {'data': {
            'epi_content': '<p>One <em>word</em>.</p><script>secret</script>',
            'epi_content2': '<p>Two<br>lines</p>', 'epi_content3': '<p>Third.</p>',
            'epi_content4': '<p>Fourth.</p><img src="https://example.com/secret-token">',
            'writer_comment': 'Unrelated author note'}})])
    rows = await crawl(ctx(maximum=1))
    assert rows[0].content == 'One word.\n\nTwo\nlines\n\nThird.\n\nFourth.'
    assert rows[0].url == mod.SITE + '/viewer/17?tg_novel=4053&tg_sort=37&tg_chapter=1.0'
    assert rows[0].number == 1
    assert all(secret not in repr(rows[0]) for secret in ['secret', 'synthetic', 'never-save', 'author note'])
    assert api.calls[-1][1] == {'_t': ['synthetic-chapter-token']}
    assert api.calls[-1][2]['Login-At'] == 'synthetic-access'
    assert not api.responses


@pytest.mark.asyncio
async def test_viewer_resume_and_next_preserve_source_number(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode', metadata(number=101)),
        ('novel/episode/content', {'data': {'epi_content': '<p>First.</p>'}}),
        ('novel/episode/next', {'episode_no': 1001}),
        ('novel/episode', metadata(ep=1001, number=102)),
        ('novel/episode/content', {'data': {'epi_content': '<p>Second.</p>'}}),
        ('novel/episode/next', {'episode_no': None})])
    rows = await crawl(ctx(mod.SITE + '/viewer/17'))
    assert [r.number for r in rows] == [101, 102]
    assert api.calls[3][1] == {'novel_no': ['4053'], 'episode_no': ['17'], 'sort_no': ['37']}
    assert not api.responses


@pytest.mark.asyncio
@pytest.mark.parametrize('code,match', [('0010', 'requires an ad'), ('0008', 'requires an ad'), ('0009', 'needs access')])
async def test_gate_is_actionable_error_never_empty_success_or_ad_bypass(monkeypatch, code, match):
    api = API(monkeypatch, [login(), ('novel/episode', (500, {'code': code, 'result': {
        'name': 'NOVEL_ERROR', 'message': 'DO-NOT-ECHO-TOKEN'}}))])
    with pytest.raises(ScrapeError, match=match) as error:
        await crawl(ctx(mod.SITE + '/viewer/17'))
    assert mod.SITE + '/viewer/17' in str(error.value)
    assert 'DO-NOT' not in str(error.value)
    assert len(api.calls) == 2


@pytest.mark.asyncio
async def test_expired_access_token_refreshes_once(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode', (401, {'code': '0004', 'result': {'name': 'AUTH_ERROR'}})),
        ('login/refresh', {'LOGINAT': 'replacement-access'}), ('novel/episode', metadata()),
        ('novel/episode/content', {'data': {'epi_content': '<p>Recovered.</p>'}})])
    rows = await crawl(ctx(mod.SITE + '/viewer/17', 1))
    assert rows[0].content == 'Recovered.'
    assert api.calls[3][2]['Login-At'] == 'replacement-access'
    assert 'Login-At' not in api.calls[2][2]


@pytest.mark.asyncio
async def test_rejected_refresh_never_loops_or_leaks(monkeypatch):
    api = API(monkeypatch, [('login/refresh', (401, {'code': '0001', 'result': {'name': 'AUTH_ERROR'}}))])
    with pytest.raises(ScrapeError, match='Replace your cookies'):
        await crawl(ctx())
    assert len(api.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['https://evil.example/novel/4053', 'http://global.novelpia.com/novel/4053',
    'https://global.novelpia.com:444/novel/4053', 'https://user@global.novelpia.com/viewer/1',
    'https://global.novelpia.com/', 'https://global.novelpia.com/viewer/0'])
async def test_invalid_start_never_sends_credentials(monkeypatch, url):
    api = API(monkeypatch, [])
    with pytest.raises(ScrapeError, match='Use a Novelpia'):
        await crawl(ctx(url))
    assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('cookies', [[], [{'name': 'TKEY', 'value': 'secret', 'expires': 1}]])
async def test_missing_or_expired_cookie_fails_before_network(monkeypatch, cookies):
    api = API(monkeypatch, [])
    context = ctx(); context.account_cookies = cookies
    with pytest.raises(ScrapeError, match='fresh Novelpia cookies'):
        await crawl(context)
    assert api.calls == []


@pytest.mark.asyncio
async def test_cross_novel_navigation_is_rejected(monkeypatch):
    API(monkeypatch, [login(), ('novel/episode/first', {'episode_no': 17}),
                     ('novel/episode', metadata(novel=999))])
    with pytest.raises(ScrapeError, match='left the selected novel'):
        await crawl(ctx())


@pytest.mark.asyncio
async def test_loop_rejected_without_fetching_again(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode', metadata()),
        ('novel/episode/content', {'data': {'epi_content': '<p>Only once.</p>'}}),
        ('novel/episode/next', {'episode_no': 17})])
    with pytest.raises(ScrapeError, match='repeated chapter navigation'):
        await crawl(ctx(mod.SITE + '/viewer/17'))
    assert not api.responses


@pytest.mark.parametrize('body', [{}, {'epi_content': ''}, {'epi_content': '<img src="private">'}, {'epi_content': ['bad']}])
def test_missing_or_image_only_content_is_failure(body):
    with pytest.raises(ScrapeError):
        mod._content(body)


@pytest.mark.asyncio
async def test_saved_checkpoint_advances_without_reopening_or_spending_access(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode/next', {'episode_no': 18}),
        ('novel/episode', metadata(ep=18, number=2)),
        ('novel/episode/content', {'data': {'epi_content': '<p>Unread.</p>'}})])
    context = ctx(mod.SITE + '/viewer/17?tg_novel=4053&tg_sort=37&tg_chapter=1', 1)
    context.resume_after_checkpoint = True
    rows = await crawl(context)
    assert [c.number for c in rows] == [2]
    assert api.calls[1][1] == {'novel_no': ['4053'], 'episode_no': ['17'], 'sort_no': ['37']}
    assert api.calls[2][1] == {'episode_no': ['18']}
    assert not api.responses


@pytest.mark.asyncio
async def test_saved_final_checkpoint_finishes_without_content_read(monkeypatch):
    api = API(monkeypatch, [login(), ('novel/episode/next', {'episode_no': None})])
    context = ctx(mod.SITE + '/viewer/17?tg_novel=4053&tg_sort=37&tg_chapter=1', 1)
    context.resume_after_checkpoint = True
    assert await crawl(context) == []
    assert not api.responses
