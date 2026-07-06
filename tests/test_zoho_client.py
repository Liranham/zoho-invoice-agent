"""Tests for ZohoClient's low-level request handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from auth.zoho_auth import ZohoAuth
from zoho.client import ZohoClient


def _client():
    auth = MagicMock(spec=ZohoAuth)
    auth.get_auth_header.return_value = {"Authorization": "Zoho-oauthtoken tok"}
    return ZohoClient(auth=auth, base_url="https://www.zohoapis.com/books/v3",
                      organization_id="org1")


def _ok_response(payload=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = payload or {"code": 0}
    resp.raise_for_status.return_value = None
    return resp


def test_json_request_sets_json_content_type():
    client = _client()
    with patch("zoho.client.req.request", return_value=_ok_response()) as mock_req:
        client.post("expenses", json={"amount": 10})
    headers = mock_req.call_args.kwargs["headers"]
    assert headers["Content-Type"] == "application/json"


def test_file_upload_does_not_force_json_content_type():
    """A multipart file upload must NOT get Content-Type: application/json —
    that overrides the boundary requests would otherwise set, and Zoho
    silently drops the attachment (manifests as 'Receipt not attached')."""
    client = _client()
    with patch("zoho.client.req.request", return_value=_ok_response()) as mock_req:
        client.post("expenses/E-1/attachment",
                    files={"attachment": ("f.pdf", b"%PDF", "application/pdf")})
    headers = mock_req.call_args.kwargs["headers"]
    assert "Content-Type" not in headers
