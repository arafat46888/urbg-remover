"""Safe remote image fetching for ``POST /api/v1/remove/url``.

Guards against SSRF by rejecting non-HTTP(S) schemes and any host that
resolves to a private, loopback, link-local or otherwise reserved address.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..errors import APIError

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 20.0
USER_AGENT = "UrBG-Remover/1.0 (+https://github.com/urbg)"


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    """Validate a URL and return it, raising :class:`APIError` when unsafe."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise APIError(
            400, "invalid_url", "Only http and https URLs are supported."
        )
    host = parsed.hostname
    if not host:
        raise APIError(400, "invalid_url", "The URL does not contain a hostname.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise APIError(400, "invalid_url", f"The hostname '{host}' could not be resolved.") from exc

    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise APIError(400, "invalid_url", f"The hostname '{host}' could not be resolved.")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise APIError(400, "invalid_url", f"The hostname '{host}' is not a valid IP address.")
        if _is_blocked_ip(ip):
            raise APIError(
                403,
                "blocked_url",
                "Requests to private or reserved network addresses are not allowed.",
            )
    return url


def fetch_image(
    url: str,
    *,
    max_bytes: int,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bytes, Optional[str]]:
    """Download an image from a public URL.

    Returns ``(data, content_type)``.  Raises :class:`APIError` on any problem.
    """
    current = validate_public_url(url)
    client = httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise APIError(400, "invalid_url", "The redirect response has no target.")
                        current = str(httpx.URL(current).join(location))
                        validate_public_url(current)
                        continue
                    if response.status_code >= 400:
                        raise APIError(
                            400,
                            "download_failed",
                            f"The remote server returned HTTP {response.status_code}.",
                        )

                    content_type = response.headers.get("content-type")
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise APIError(
                            413,
                            "file_too_large",
                            f"The remote image is larger than the {max_bytes // (1024 * 1024)} MB limit.",
                        )

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise APIError(
                                413,
                                "file_too_large",
                                f"The remote image is larger than the {max_bytes // (1024 * 1024)} MB limit.",
                            )
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data:
                        raise APIError(400, "download_failed", "The remote server returned an empty response.")
                    return data, content_type
            except httpx.TimeoutException as exc:
                raise APIError(408, "download_timeout", "The remote server took too long to respond.") from exc
            except httpx.HTTPError as exc:
                raise APIError(400, "download_failed", f"Could not download the image: {exc}") from exc

        raise APIError(400, "invalid_url", "Too many redirects while downloading the image.")
    finally:
        client.close()
