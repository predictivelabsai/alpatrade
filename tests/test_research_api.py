"""DB-free mobile research contract and tenant boundary tests."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from engine.research_api import research_router
from engine.leaderboard import store, perf, clone_bt
from engine.publicmarkets import hedge_funds as hf

USER = {"user_id": "00000000-0000-0000-0000-000000000001", "email": "owner@example.test"}


def require_user():
    raise HTTPException(401, "Sign in required")


def optional_user():
    return None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(research_router(require_user, optional_user))
    return TestClient(app)


def test_private_routes_require_auth(client):
    for path in ("strategies", "hedge-funds", "hedge-funds/performance", "hedge-funds/activists", "ipos", "ipos/pipeline"):
        assert client.get('/v2/' + path).status_code == 401
    assert client.post('/v2/strategies/1/clone').status_code == 401


def test_public_ranking_and_no_identity_leaks(client, monkeypatch):
    monkeypatch.setattr(store, 'list_public', lambda: [
        dict(id=1, name='Backtest', kind='backtest', user_id='secret', user_email='secret@example.test', author_name='Author'),
        dict(id=2, name='Live', kind='live', user_id='secret', author_name='Author')])
    monkeypatch.setattr(perf, 'strategy_metrics', lambda r: {'is_backtest': r['kind'] == 'backtest', 'annualised_pct': None})
    response = client.get('/v2/leaderboard')
    assert response.status_code == 200
    rows = response.json()['strategies']
    assert [r['id'] for r in rows] == [2, 1]
    assert 'secret' not in response.text
    assert client.get('/v2/leaderboard?kind=backtest&q=back').json()['strategies'][0]['rank'] == 2
    assert client.get('/v2/leaderboard?limit=0').status_code == 422


def test_private_strategy_visibility(client, monkeypatch):
    seen = []
    monkeypatch.setattr(store, 'get_visible', lambda sid, uid: seen.append((sid, uid)))
    assert client.get('/v2/strategies/9').status_code == 404
    assert seen == [(9, None)]


def test_cloning_uses_authenticated_owner_and_reuses_existing(client, monkeypatch):
    client.app.dependency_overrides[require_user] = lambda: USER
    seen = []
    monkeypatch.setattr(clone_bt, 'clone_strategy', lambda sid, user: (seen.append((sid, user)) or (42, False)))
    response = client.post('/v2/strategies/5/clone', json={'user_id': 'attacker'})
    assert response.json() == {'id': 42, 'created': False}
    assert seen == [(5, USER)]


def test_update_delete_are_owner_scoped(client, monkeypatch):
    client.app.dependency_overrides[require_user] = lambda: USER
    seen = []
    monkeypatch.setattr(store, 'update', lambda sid, uid, **kw: seen.append(uid) or False)
    monkeypatch.setattr(store, 'delete', lambda sid, uid: seen.append(uid) or False)
    assert client.put('/v2/strategies/2', json={'name': 'Changed'}).status_code == 404
    assert client.delete('/v2/strategies/2').status_code == 404
    assert seen == [USER['user_id'], USER['user_id']]


def test_screener_filters_and_performance_method(client, monkeypatch):
    client.app.dependency_overrides[require_user] = lambda: USER
    monkeypatch.setattr(hf, 'filing_periods', lambda: [])
    monkeypatch.setattr(hf, 'default_period', lambda _: '2026-06-30')
    seen = []
    monkeypatch.setattr(hf, 'screen_13f', lambda **kw: seen.append(kw) or {'rows': [], 'period': kw['period']})
    response = client.get('/v2/hedge-funds?q=Berkshire&holds=AAPL&min_aum=1b&sort=ttm')
    assert response.status_code == 200
    assert seen[0]['period'] == '2026-06-30'
    assert seen[0]['holds'] == 'AAPL'
    assert seen[0]['min_aum'] == '1b'
    monkeypatch.setattr(hf, 'performance_rows', lambda method: {'funds': [], 'labels': []})
    assert client.get('/v2/hedge-funds/performance?method=follow_filing').json()['method'] == 'follow_filing'
    assert client.get('/v2/hedge-funds/performance?method=invalid').status_code == 422


def test_backtest_jobs_are_owner_scoped(client, monkeypatch):
    client.app.dependency_overrides[require_user] = lambda: USER
    monkeypatch.setattr(store, 'get', lambda sid: {'id': sid, 'user_id': 'another-user'})
    assert client.post('/v2/strategies/5/backtest').status_code == 404
    monkeypatch.setattr(store, 'get', lambda sid: {'id': sid, 'user_id': USER['user_id']})
    monkeypatch.setattr(clone_bt, 'start_backtest', lambda sid, uid: 'job123')
    assert client.post('/v2/strategies/5/backtest').json() == {'job_id': 'job123'}
    monkeypatch.setitem(clone_bt.JOBS, 'private-job', {'key': 'another-user:5', 'state': 'running'})
    assert client.get('/v2/strategy-backtests/private-job').status_code == 404
    monkeypatch.setitem(clone_bt.JOBS, 'job123', {'key': USER['user_id'] + ':5', 'state': 'done', 'markdown': 'Done', 'strategy_id': 5})
    result = client.get('/v2/strategy-backtests/job123')
    assert result.json()['state'] == 'done'
    assert 'key' not in result.json()


def test_landing_android_download_uses_mobile_release():
    from engine.web.ph_landing import latest_apk_url
    assert latest_apk_url() == (
        "https://github.com/predictivelabsai/alpatrade-mobile/"
        "releases/latest/download/alpatrade-latest.apk"
    )
