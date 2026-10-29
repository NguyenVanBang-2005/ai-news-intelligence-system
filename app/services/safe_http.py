"""Download helpers for URLs we do not control: pinned DNS, redirect checks, size limits."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeFeedUrlError(ValueError):
    pass


class ResponseTooLargeError(ValueError):
    pass


class TooManyRedirectsError(ValueError):
    """The server kept redirecting past max_redirects."""


def resolve_public_addresses(url: str) -> tuple[str, list[str], int]:
    """Resolve the host once; return (hostname, checked IPs with IPv4 first, port) or raise."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeFeedUrlError("Only public HTTP(S) feed URLs are accepted")
    port = parsed.port or (80 if parsed.scheme == "http" else 443)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port)
    except socket.gaierror as exc:
        raise UnsafeFeedUrlError("Feed hostname could not be resolved") from exc
    ips = list(dict.fromkeys(address[4][0].split("%")[0] for address in addresses))
    if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
        raise UnsafeFeedUrlError("Private or local feed addresses are not accepted")
    ips.sort(key=lambda ip: ipaddress.ip_address(ip).version)
    return parsed.hostname, ips, port


def resolve_public_address(url: str) -> tuple[str, str, int]:
    """Like resolve_public_addresses, but return only the preferred IP."""
    hostname, ips, port = resolve_public_addresses(url)
    return hostname, ips[0], port


class PinnedTransport(httpx.BaseTransport):
    """Check every request's host, then connect only to the IPs that were checked.

    The host is resolved once per request; if one IP cannot be reached the next checked IP
    is tried. With rewrite=False the request is only checked, so tests can serve fixtures
    by URL.
    """

    def __init__(self, inner: httpx.BaseTransport | None = None, rewrite: bool = True):
        self.inner = inner or httpx.HTTPTransport()
        self.rewrite = rewrite

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        hostname, ips, port = resolve_public_addresses(str(request.url))
        if not self.rewrite:
            return self.inner.handle_request(request)
        host_header = request.headers["Host"]
        original_url = request.url
        for index, ip in enumerate(ips):
            request.url = original_url.copy_with(host=ip, port=port)
            request.headers["Host"] = host_header
            # TLS still verifies the certificate against the original hostname.
            request.extensions["sni_hostname"] = hostname
            try:
                return self.inner.handle_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if index == len(ips) - 1:
                    raise
        raise UnsafeFeedUrlError("No address to connect to")  # unreachable: ips is not empty

    def close(self) -> None:
        self.inner.close()


def make_client(timeout: float, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Build a client that never follows redirects itself and ignores proxy env variables."""
    pinned = PinnedTransport() if transport is None else PinnedTransport(transport, rewrite=False)
    return httpx.Client(
        timeout=timeout, follow_redirects=False, trust_env=False, transport=pinned
    )


def open_stream(
    client: httpx.Client, url: str, headers: dict[str, str], max_redirects: int
) -> httpx.Response:
    """Send GET and follow up to max_redirects redirects; the caller must close the response."""
    for hops in range(max_redirects + 1):
        request = client.build_request("GET", url, headers=headers)
        response = client.send(request, stream=True)
        if not response.is_redirect:
            response.extensions["redirects"] = hops
            return response
        location = response.headers.get("location")
        response.close()
        if not location:
            raise ValueError("Redirect without a Location header")
        url = urljoin(url, location)
    raise TooManyRedirectsError("Too many redirects")


def read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    """Read the decoded body, stopping as soon as it passes max_bytes."""
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLargeError(f"Response exceeds {max_bytes} bytes")
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ResponseTooLargeError(f"Response exceeds {max_bytes} bytes")
    return bytes(body)
