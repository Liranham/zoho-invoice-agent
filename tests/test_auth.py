"""Tests for the Zoho OAuth2 token manager."""

import time
from unittest.mock import patch, MagicMock

from auth.zoho_auth import ZohoAuth, REFRESH_MARGIN_SECONDS


def _make_auth():
    return ZohoAuth(
        client_id="test_client_id",
        client_secret="test_secret",
        refresh_token="test_refresh",
        accounts_url="https://accounts.zoho.com",
    )


@patch("auth.zoho_auth.requests.post")
def test_get_access_token_refreshes_on_first_call(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "tok_123", "expires_in": 3600},
    )
    auth = _make_auth()
    token = auth.get_access_token()

    assert token == "tok_123"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "oauth/v2/token" in args[0]


@patch("auth.zoho_auth.requests.post")
def test_get_access_token_uses_cache(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "tok_123", "expires_in": 3600},
    )
    auth = _make_auth()
    auth.get_access_token()
    auth.get_access_token()

    # Only called once — second call uses cache
    assert mock_post.call_count == 1


@patch("auth.zoho_auth.requests.post")
def test_get_access_token_refreshes_when_near_expiry(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "tok_new", "expires_in": 3600},
    )
    auth = _make_auth()
    auth._access_token = "tok_old"
    auth._expires_at = time.time() + 10  # expires very soon

    token = auth.get_access_token()
    assert token == "tok_new"
    mock_post.assert_called_once()


@patch("auth.zoho_auth.requests.post")
def test_get_auth_header(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "tok_abc", "expires_in": 3600},
    )
    auth = _make_auth()
    header = auth.get_auth_header()

    assert header == {"Authorization": "Zoho-oauthtoken tok_abc"}


@patch("auth.zoho_auth.requests.post")
def test_refresh_raises_on_error_response(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"error": "invalid_code"},
    )
    auth = _make_auth()
    try:
        auth.get_access_token()
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "invalid_code" in str(e)
