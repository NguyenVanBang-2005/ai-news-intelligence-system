"""client_ip(): X-Forwarded-For is believed only from trusted proxies (TRUSTED_PROXY_CIDRS).

No network: requests are built from ASGI scopes, and the rate-limit cases go through the
TestClient with a chosen socket peer.
"""

from ipaddress import ip_network

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from starlette.requests import Request

from app.api.deps import client_ip
from app.core.config import Settings, settings
from tests.pg_support import client_for

PROXY_NET = "172.28.0.0/16"
PROXY = "172.28.0.3"     # e.g. the Nginx container
OUTSIDER = "203.0.113.7"  # a client connecting directly


@pytest.fixture
def trust_proxy_net(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", [ip_network(PROXY_NET)])


def request_from(peer: str, *forwarded_for: str) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded_for]
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "client": (peer, 40000),
    })


# --- client_ip ----------------------------------------------------------------------------


@pytest.mark.usefixtures("trust_proxy_net")
def test_untrusted_peer_ignores_a_forged_header() -> None:
    assert client_ip(request_from(OUTSIDER, "1.2.3.4")) == OUTSIDER


@pytest.mark.usefixtures("trust_proxy_net")
def test_trusted_peer_gives_the_forwarded_client() -> None:
    assert client_ip(request_from(PROXY, "1.2.3.4")) == "1.2.3.4"


@pytest.mark.usefixtures("trust_proxy_net")
def test_trusted_hops_on_the_right_are_skipped() -> None:
    assert client_ip(request_from(PROXY, "9.9.9.9, 172.28.0.5")) == "9.9.9.9"


@pytest.mark.usefixtures("trust_proxy_net")
def test_only_the_rightmost_untrusted_address_counts() -> None:
    # "6.6.6.6" was written by the client itself; the proxy appended the real address.
    assert client_ip(request_from(PROXY, "6.6.6.6, 9.9.9.9")) == "9.9.9.9"


@pytest.mark.usefixtures("trust_proxy_net")
def test_several_header_lines_are_read_as_one_list() -> None:
    assert client_ip(request_from(PROXY, "6.6.6.6", "9.9.9.9")) == "9.9.9.9"


@pytest.mark.usefixtures("trust_proxy_net")
@pytest.mark.parametrize("header", ["not-an-ip", "", "1.2.3.4, garbage", "1.2.3.4,,"])
def test_malformed_header_gives_the_peer(header: str) -> None:
    assert client_ip(request_from(PROXY, header)) == PROXY


@pytest.mark.usefixtures("trust_proxy_net")
def test_missing_header_or_only_trusted_hops_give_the_peer() -> None:
    assert client_ip(request_from(PROXY)) == PROXY
    assert client_ip(request_from(PROXY, "172.28.0.9, 172.28.0.5")) == PROXY


@pytest.mark.usefixtures("trust_proxy_net")
def test_ipv4_mapped_peer_is_recognised_as_trusted() -> None:
    assert client_ip(request_from(f"::ffff:{PROXY}", "1.2.3.4")) == "1.2.3.4"


@pytest.mark.usefixtures("trust_proxy_net")
def test_a_non_ip_peer_is_never_trusted() -> None:
    assert client_ip(request_from("testclient", "1.2.3.4")) == "testclient"


def test_empty_trusted_list_always_gives_the_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", [])

    assert client_ip(request_from(PROXY, "1.2.3.4")) == PROXY
    assert client_ip(request_from("127.0.0.1", "1.2.3.4")) == "127.0.0.1"


# --- configuration ------------------------------------------------------------------------


def test_cidrs_are_parsed_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", " 172.28.0.0/16 , 10.0.0.1, ::1/128 ")

    assert Settings(_env_file=None).trusted_proxy_cidrs == [
        ip_network("172.28.0.0/16"), ip_network("10.0.0.1/32"), ip_network("::1/128"),
    ]


def test_empty_cidrs_trust_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "")

    assert Settings(_env_file=None).trusted_proxy_cidrs == []


@pytest.mark.parametrize("value", ["nope", "172.28.0.0/99", "172.28.0.5/16", "1.2.3.4,bad"])
def test_invalid_cidrs_fail_at_startup(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", value)

    with pytest.raises(ValidationError, match="TRUSTED_PROXY_CIDRS"):
        Settings(_env_file=None)


# --- rate limit keyed by client_ip ------------------------------------------------------------


@pytest.fixture
def offline_search(monkeypatch: pytest.MonkeyPatch) -> None:
    news_search = pytest.importorskip("app.services.news_search")
    from tests.test_news_search import FakeEmbedder

    monkeypatch.setattr(news_search, "get_embedding_model", lambda: FakeEmbedder())
    monkeypatch.setattr(settings, "ai_search_rate_per_minute", 30)


def searches_from(engine: Engine, peer: str, count: int) -> list[int]:
    statuses = []
    for client in client_for(engine, client=(peer, 40000)):
        client.headers.pop("X-Admin-Token", None)
        for number in range(count):
            response = client.post(
                "/api/v1/ai/search",
                json={"input": "ai regulation"},
                headers={"X-Forwarded-For": f"198.51.100.{number + 1}"},
            )
            statuses.append(response.status_code)
    return statuses


@pytest.mark.usefixtures("trust_proxy_net", "offline_search")
def test_forged_headers_from_an_untrusted_peer_share_one_bucket(engine: Engine) -> None:
    statuses = searches_from(engine, OUTSIDER, 31)

    assert statuses[:30] == [200] * 30
    assert statuses[30] == 429


@pytest.mark.usefixtures("trust_proxy_net", "offline_search")
def test_clients_behind_a_trusted_proxy_get_their_own_bucket(engine: Engine) -> None:
    statuses = searches_from(engine, PROXY, 31)

    assert 429 not in statuses
    assert statuses == [200] * 31
