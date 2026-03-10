"""Tests for HTTP retry logic."""
import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import Timeout, ConnectionError as ReqConnectionError

from cdawebmcp.http import request_with_retry


def test_request_success():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        resp = request_with_retry("https://example.com")
        assert resp.status_code == 200
        mock_get.assert_called_once()


def test_request_retry_on_timeout():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_resp = MagicMock(status_code=200)
        mock_get.side_effect = [Timeout(), Timeout(), mock_resp]
        resp = request_with_retry("https://example.com", retries=3, backoff=0)
        assert resp.status_code == 200
        assert mock_get.call_count == 3


def test_request_raises_after_retries():
    with patch("cdawebmcp.http.requests.get") as mock_get:
        mock_get.side_effect = Timeout()
        with pytest.raises(Timeout):
            request_with_retry("https://example.com", retries=2, backoff=0)
        assert mock_get.call_count == 2
