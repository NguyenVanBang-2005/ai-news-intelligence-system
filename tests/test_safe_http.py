import socket
from collections.abc import Iterator

import httpx
import pytest

from app.services import safe_http
from app.services.content_extractor import ArticleContentExtractor
from app.services.feed import FeedClient, FeedTooLargeError
from app.services.safe_http import (
    PinnedTransport,
    ResponseTooLargeError,
    UnsafeFeedUrlError,
    open_stream,
    read_limited,
    resolve_public_address,
)

PUBLIC = "93.184.216.34"


def fake_dns(monkeypatch: pytest.MonkeyPatch, *answers: list[str]) -> list[str]:
    """Each lookup returns the next list of IPs (the last one repeats); returns the lookups."""
    lookups: list[str] = []

    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        lookups.append(host)
        ips = answers[min(len(lookups), len(answers)) - 1]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return lookups


def recording_inner(seen: list[httpx.Request], **response_kwargs: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, **response_kwargs)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"])
def test_non_public_address_is_rejected(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    fake_dns(monkeypatch, [ip])

    with pytest.raises(UnsafeFeedUrlError):
        resolve_public_address("https://evil.example/feed")


def test_one_private_address_among_public_ones_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC, "10.0.0.5"])

    with pytest.raises(UnsafeFeedUrlError):
        resolve_public_address("https://mixed.example/feed")


def test_rebinding_after_the_check_cannot_change_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups = fake_dns(monkeypatch, [PUBLIC], ["127.0.0.1"])
    seen: list[httpx.Request] = []
    client = httpx.Client(transport=PinnedTransport(recording_inner(seen)))

    client.get("https://rebind.example/feed")

    assert len(lookups) == 1  # resolved once; a second answer is never asked for
    assert seen[0].url.host == PUBLIC


def test_host_header_and_sni_keep_the_original_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC])
    seen: list[httpx.Request] = []
    client = httpx.Client(transport=PinnedTransport(recording_inner(seen)))

    client.get("https://news.example:8443/rss")

    request = seen[0]
    assert (request.url.host, request.url.port) == (PUBLIC, 8443)
    assert request.headers["Host"] == "news.example:8443"
    assert request.extensions["sni_hostname"] == "news.example"


def test_redirect_to_private_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        ip = "10.0.0.5" if host == "internal.example" else PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://internal.example/admin"})

    client = httpx.Client(
        transport=PinnedTransport(httpx.MockTransport(handler)), follow_redirects=False
    )

    with pytest.raises(UnsafeFeedUrlError):
        open_stream(client, "https://ok.example/start", {}, max_redirects=3)
    assert len(seen) == 1  # the private hop was never requested


def test_redirect_to_other_scheme_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC])
    handler = lambda r: httpx.Response(302, headers={"Location": "ftp://ok.example/f"})  # noqa: E731
    client = httpx.Client(transport=PinnedTransport(httpx.MockTransport(handler)))

    with pytest.raises(UnsafeFeedUrlError):
        open_stream(client, "https://ok.example/start", {}, max_redirects=3)


def stream_of(sent: list[int], chunks: int = 1000) -> httpx.Response:
    def body() -> Iterator[bytes]:
        for index in range(chunks):
            sent.append(index)
            yield b"x" * 100

    return httpx.Response(200, content=body())


def test_read_limited_stops_mid_stream() -> None:
    sent: list[int] = []

    with pytest.raises(ResponseTooLargeError):
        read_limited(stream_of(sent), 1000)

    assert len(sent) < 20


def test_read_limited_rejects_large_content_length_before_reading() -> None:
    sent: list[int] = []
    response = stream_of(sent)
    response.headers["Content-Length"] = "999999"

    with pytest.raises(ResponseTooLargeError):
        read_limited(response, 1000)

    assert sent == []


def test_feed_client_connects_to_checked_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC], ["127.0.0.1"])
    seen: list[httpx.Request] = []
    feed = b'<rss version="2.0"><channel><title>T</title></channel></rss>'
    monkeypatch.setattr(
        safe_http.httpx, "HTTPTransport", lambda: recording_inner(seen, content=feed)
    )

    FeedClient(5).fetch("https://feed.example/rss", 10)

    assert seen[0].url.host == PUBLIC
    assert seen[0].headers["Host"] == "feed.example"


def test_feed_client_rejects_private_host(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, ["127.0.0.1"])

    with pytest.raises(UnsafeFeedUrlError):
        FeedClient(5, transport=httpx.MockTransport(lambda r: httpx.Response(200))).fetch(
            "https://feed.example/rss", 10
        )


def extractor(handler, max_bytes: int = 1000) -> ArticleContentExtractor:
    return ArticleContentExtractor(
        5, max_bytes, 3, transport=httpx.MockTransport(handler)
    )


def test_article_download_stops_when_body_is_too_large(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC])
    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        response = stream_of(sent)
        response.headers["Content-Type"] = "text/html"
        return response

    assert extractor(handler)._download_html("https://a.example/post") is None
    assert len(sent) < 20


def test_article_download_returns_html(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC])
    handler = lambda r: httpx.Response(  # noqa: E731
        200, content="<html>Trí tuệ</html>".encode(), headers={"Content-Type": "text/html"}
    )

    assert extractor(handler)._download_html("https://a.example/post") == "<html>Trí tuệ</html>"


def test_article_download_rejects_private_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        ip = "127.0.0.1" if host == "local.example" else PUBLIC
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    handler = lambda r: httpx.Response(  # noqa: E731
        302, headers={"Location": "http://local.example/"}
    )

    assert extractor(handler)._download_html("https://a.example/post") is None


def test_feed_too_large_error_type_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [PUBLIC])
    client = FeedClient(
        5, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 50)),
        max_feed_bytes=10,
    )

    with pytest.raises(FeedTooLargeError):
        client.fetch("https://feed.example/rss", 10)


V6 = "2606:4700:4700::1111"


def failing_first_inner(seen: list[str], failing: set[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host in failing:
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200)

    return httpx.MockTransport(handler)


def test_ipv4_is_tried_before_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [V6, PUBLIC])
    tried: list[str] = []
    client = httpx.Client(transport=PinnedTransport(failing_first_inner(tried, set())))

    client.get("https://dual.example/")

    assert tried == [PUBLIC]


def test_next_checked_ip_is_tried_when_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups = fake_dns(monkeypatch, [V6, PUBLIC], ["127.0.0.1"])
    tried: list[str] = []
    client = httpx.Client(transport=PinnedTransport(failing_first_inner(tried, {PUBLIC})))

    response = client.get("https://dual.example/")

    assert response.status_code == 200
    assert tried == [PUBLIC, V6]
    assert len(lookups) == 1  # the loopback answer was never asked for or used


def test_error_is_raised_when_every_ip_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_dns(monkeypatch, [V6, PUBLIC])
    tried: list[str] = []
    client = httpx.Client(transport=PinnedTransport(failing_first_inner(tried, {V6, PUBLIC})))

    with pytest.raises(httpx.ConnectError):
        client.get("https://dual.example/")

    assert tried == [PUBLIC, V6]


def test_private_ip_mixed_with_public_ones_is_still_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, [V6, PUBLIC, "192.168.0.9"])
    tried: list[str] = []
    client = httpx.Client(transport=PinnedTransport(failing_first_inner(tried, set())))

    with pytest.raises(UnsafeFeedUrlError):
        client.get("https://mixed.example/")

    assert tried == []
