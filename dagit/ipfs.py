"""IPFS HTTP API wrapper for content-addressed storage."""

import json
from typing import Any

import requests

DEFAULT_API_URL = "http://localhost:5001/api/v0"


class IPFSClient:
    """Client for IPFS HTTP API."""

    def __init__(self, api_url: str = DEFAULT_API_URL):
        self.api_url = api_url.rstrip("/")

    def _post(self, endpoint: str, timeout: int = 10, **kwargs) -> requests.Response:
        """Make a POST request to the IPFS API."""
        url = f"{self.api_url}/{endpoint}"
        response = requests.post(url, timeout=timeout, **kwargs)
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

    def key_list(self) -> list[dict]:
        """List all keys in the IPFS keystore.

        Returns:
            List of dicts with 'Name' and 'Id' fields
        """
        response = self._post("key/list")
        return response.json().get("Keys", [])

    def key_import(self, name: str, pem_body: str) -> str:
        """Import a PEM-encoded private key into the IPFS keystore.

        Args:
            name: Key name in the keystore
            pem_body: PEM-encoded PKCS8 private key

        Returns:
            Peer ID of the imported key
        """
        response = self._post(
            "key/import",
            params={"arg": name, "format": "pem-pkcs8-cleartext"},
            files={"file": ("key.pem", pem_body.encode("utf-8"))},
        )
        return response.json().get("Id", "")

    def name_publish(self, cid: str, key_name: str = "self") -> str:
        """Publish an IPNS name pointing to a CID.

        Args:
            cid: CID to publish
            key_name: Key name in the keystore (default "self")

        Returns:
            Published IPNS name
        """
        response = self._post(
            "name/publish",
            params={"arg": f"/ipfs/{cid}", "key": key_name},
            timeout=60,
        )
        return response.json().get("Name", "")

    def name_resolve(self, ipns_name: str, timeout_s: int = 30) -> str:
        """Resolve an IPNS name to a CID.

        Args:
            ipns_name: IPNS name to resolve
            timeout_s: Timeout in seconds (default 30)

        Returns:
            Resolved CID (without /ipfs/ prefix)
        """
        response = self._post(
            "name/resolve",
            params={"arg": ipns_name},
            timeout=timeout_s,
        )
        path = response.json().get("Path", "")
        return path.removeprefix("/ipfs/")

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


def key_list() -> list[dict]:
    """List keys using default client."""
    return get_client().key_list()


def key_import(name: str, pem_body: str) -> str:
    """Import key using default client."""
    return get_client().key_import(name, pem_body)


def name_publish(cid: str, key_name: str = "self") -> str:
    """Publish IPNS name using default client."""
    return get_client().name_publish(cid, key_name)


def name_resolve(ipns_name: str, timeout_s: int = 30) -> str:
    """Resolve IPNS name using default client."""
    return get_client().name_resolve(ipns_name, timeout_s)
