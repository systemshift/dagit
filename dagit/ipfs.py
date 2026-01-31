"""IPFS HTTP API wrapper for content-addressed storage."""

import json
from typing import Any

import requests

DEFAULT_API_URL = "http://localhost:5001/api/v0"


class IPFSClient:
    """Client for IPFS HTTP API."""

    def __init__(self, api_url: str = DEFAULT_API_URL):
        self.api_url = api_url.rstrip("/")

    def _post(self, endpoint: str, **kwargs) -> requests.Response:
        """Make a POST request to the IPFS API."""
        url = f"{self.api_url}/{endpoint}"
        response = requests.post(url, **kwargs)
        response.raise_for_status()
        return response

    def add(self, content: str | bytes | dict) -> str:
        """Add content to IPFS.

        Args:
            content: String, bytes, or dict (will be JSON-encoded)

        Returns:
            CID of the added content
        """
        if isinstance(content, dict):
            content = json.dumps(content, separators=(",", ":"))
        if isinstance(content, str):
            content = content.encode("utf-8")

        files = {"file": ("data", content)}
        response = self._post("add", files=files)
        result = response.json()
        return result["Hash"]

    def get(self, cid: str) -> bytes:
        """Get content from IPFS by CID.

        Args:
            cid: Content identifier

        Returns:
            Raw bytes of the content
        """
        response = self._post("cat", params={"arg": cid})
        return response.content

    def get_json(self, cid: str) -> dict:
        """Get and parse JSON content from IPFS.

        Args:
            cid: Content identifier

        Returns:
            Parsed JSON as dict
        """
        content = self.get(cid)
        return json.loads(content)

    def pin(self, cid: str) -> bool:
        """Pin content to prevent garbage collection.

        Args:
            cid: Content identifier to pin

        Returns:
            True if pinned successfully
        """
        self._post("pin/add", params={"arg": cid})
        return True

    def is_available(self) -> bool:
        """Check if IPFS daemon is available.

        Returns:
            True if IPFS API is reachable
        """
        try:
            response = requests.post(f"{self.api_url}/id", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False


# Default client instance
_client: IPFSClient | None = None


def get_client() -> IPFSClient:
    """Get the default IPFS client."""
    global _client
    if _client is None:
        _client = IPFSClient()
    return _client


def add(content: str | bytes | dict) -> str:
    """Add content to IPFS using default client."""
    return get_client().add(content)


def get(cid: str) -> bytes:
    """Get content from IPFS using default client."""
    return get_client().get(cid)


def get_json(cid: str) -> dict:
    """Get JSON content from IPFS using default client."""
    return get_client().get_json(cid)


def pin(cid: str) -> bool:
    """Pin content using default client."""
    return get_client().pin(cid)


def is_available() -> bool:
    """Check if IPFS is available using default client."""
    return get_client().is_available()
