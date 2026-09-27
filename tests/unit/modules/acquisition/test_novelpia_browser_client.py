import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest

from novelwiki.modules.acquisition.adapters.outbound.scraper import novelpia_browser as mod
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ScrapeContext


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(mod.settings, 'NOVELPIA_BROWSER_ENABLED', True)
    monkeypatch.setattr(mod.settings, 'NOVELPIA_BROWSER_URL', 'http://novelpia-browser:8079')
    monkeypatch.setattr(mod.settings, 'NOVELPIA_BROWSER_TOKEN', 'synthetic-service-token')
    return ScrapeContext(start_url='https://global.novelpia.com/viewer/17',session=object(),
                         account_cookies=[{'name':'TKEY','value':'synthetic-account-token'}],
                         report_stage=AsyncMock())


def mock_http(monkeypatch, responses):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        async def __aenter__(self):return self
        async def __aexit__(self, *args):pass
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            calls.append((method,url,kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):raise response
            yield response
    monkeypatch.setattr(mod.httpx,'AsyncClient',Client)
    return calls


@pytest.mark.asyncio
async def test_private_rpc_is_scoped_and_does_not_follow_redirects(monkeypatch, context):
    calls=mock_http(monkeypatch,[httpx.Response(200,json={'status':'completed'})])
    assert await mod.complete_ad(context,17)=='completed'
    method,url,options=calls[0]
    assert method=='POST' and url=='http://novelpia-browser:8079/unlock'
    assert options['json']['episode_id']==17
    assert options['json']['cookies']==context.account_cookies
    assert options['headers']=={'X-Tideglass-Sidecar-Token':'synthetic-service-token'}
    context.report_stage.assert_awaited_once_with('Watching Novelpia ad')


@pytest.mark.asyncio
@pytest.mark.parametrize('response',[
    httpx.Response(302,headers={'location':'https://evil.example'}),
    httpx.Response(401,json={'secret':'synthetic-account-token'}),
    httpx.Response(200,content=b'x'*4097),
    httpx.Response(200,json={'status':['completed']}),
    httpx.Response(200,json={'status':'unexpected-secret'}),
    httpx.Response(200,content=b'bad json'),
])
async def test_invalid_responses_are_safe_failures(monkeypatch,context,response):
    calls=mock_http(monkeypatch,[response])
    assert await mod.complete_ad(context,17)=='unavailable'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_service_deadline_preserves_timeout_status(monkeypatch, context):
    mock_http(monkeypatch, [httpx.Response(504, json={'status': 'timeout'})])
    assert await mod.complete_ad(context, 17) == 'timeout'


@pytest.mark.asyncio
async def test_cancellation_closes_inflight_http_operation(monkeypatch,context):
    started=asyncio.Event();closed=asyncio.Event()
    async def slow(*args):
        started.set()
        try:await asyncio.Event().wait()
        finally:closed.set()
    class CancelledByUser(Exception):pass
    async def cancel():
        if started.is_set():raise CancelledByUser()
    context.cancel_check=cancel
    monkeypatch.setattr(mod,'_post',slow)
    monkeypatch.setattr(mod,'POLL_SECONDS',0.01)
    with pytest.raises(CancelledByUser):await mod.complete_ad(context,17)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_busy_browser_wait_is_bounded_and_cancellable(monkeypatch,context):
    monkeypatch.setattr(mod,'QUEUE_WAIT_SECONDS',0)
    calls=mock_http(monkeypatch,[httpx.Response(429)])
    assert await mod.complete_ad(context,17)=='busy'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_disabled_or_missing_token_never_sends_cookies(monkeypatch,context):
    calls=mock_http(monkeypatch,[])
    monkeypatch.setattr(mod.settings,'NOVELPIA_BROWSER_ENABLED',False)
    assert await mod.complete_ad(context,17)=='disabled'
    monkeypatch.setattr(mod.settings,'NOVELPIA_BROWSER_ENABLED',True)
    monkeypatch.setattr(mod.settings,'NOVELPIA_BROWSER_TOKEN','')
    monkeypatch.setattr(mod.settings,'SIDECAR_AUTH_TOKEN','')
    assert await mod.complete_ad(context,17)=='unavailable'
    assert calls==[]
