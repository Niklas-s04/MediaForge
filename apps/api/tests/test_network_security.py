from __future__ import annotations

import socket

import pytest

from apps.api.app.network_security import RemoteUrlPolicyError, validate_remote_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://user:password@example.com/video",
        "http://service.local/video",
    ],
)
def test_remote_url_policy_blocks_local_or_unsafe_targets(url):
    with pytest.raises(RemoteUrlPolicyError):
        validate_remote_url(url, resolve=False)


def test_remote_url_policy_rejects_dns_name_with_private_answer(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 443)),
        ],
    )

    with pytest.raises(RemoteUrlPolicyError):
        validate_remote_url("https://example.com/media", resolve=True)


def test_remote_url_policy_allows_public_https_answer(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )

    assert validate_remote_url("https://example.com/media", resolve=True) == "https://example.com/media"
