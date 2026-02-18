"""Ed25519 keypair and DID management for agent identity."""

import base64
import json
from pathlib import Path

from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import RawEncoder
from nacl.exceptions import BadSignatureError

DAGIT_DIR = Path.home() / ".dagit"
MEMEX_CONFIG_DIR = Path.home() / ".config" / "memex"
IDENTITY_FILE = MEMEX_CONFIG_DIR / "identity.json"

# Multicodec prefix for Ed25519 public key (0xed01)
ED25519_MULTICODEC = b"\xed\x01"


def _encode_did_key(public_key_bytes: bytes) -> str:
    """Encode public key as did:key using multibase base58btc."""
    # Multicodec-prefixed key
    prefixed = ED25519_MULTICODEC + public_key_bytes

    # Base58btc encode (Bitcoin alphabet)
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(prefixed, "big")
    encoded = ""
    while num:
        num, rem = divmod(num, 58)
        encoded = ALPHABET[rem] + encoded

    # Handle leading zeros
    for byte in prefixed:
        if byte == 0:
            encoded = "1" + encoded
        else:
            break

    # did:key format with 'z' multibase prefix for base58btc
    return f"did:key:z{encoded}"


def _decode_did_key(did: str) -> bytes:
    """Decode did:key to raw public key bytes."""
    if not did.startswith("did:key:z"):
        raise ValueError(f"Invalid did:key format: {did}")

    encoded = did[9:]  # Remove "did:key:z"

    # Base58btc decode
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for char in encoded:
        num = num * 58 + ALPHABET.index(char)

    # Convert to bytes (34 bytes: 2 prefix + 32 key)
    prefixed = num.to_bytes(34, "big")

    # Verify and strip multicodec prefix
    if prefixed[:2] != ED25519_MULTICODEC:
        raise ValueError("Invalid multicodec prefix for Ed25519 key")

    return prefixed[2:]


def create() -> dict:
    """Create a new Ed25519 identity and save to disk.

    Returns:
        dict with 'did', 'public_key', and 'private_key' (all base64)
    """
    MEMEX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key

    public_bytes = verify_key.encode()
    private_bytes = signing_key.encode()

    identity = {
        "did": _encode_did_key(public_bytes),
        "public_key": base64.b64encode(public_bytes).decode("ascii"),
        "private_key": base64.b64encode(private_bytes).decode("ascii"),
    }

    IDENTITY_FILE.write_text(json.dumps(identity, indent=2))
    return identity


def load() -> dict | None:
    """Load identity from disk.

    Returns:
        Identity dict or None if not found
    """
    if not IDENTITY_FILE.exists():
        return None

    return json.loads(IDENTITY_FILE.read_text())


def get_signing_key() -> SigningKey:
    """Get the signing key for the current identity."""
    identity = load()
    if not identity:
        raise RuntimeError("No identity found. Run 'dagit init' first.")

    private_bytes = base64.b64decode(identity["private_key"])
    return SigningKey(private_bytes)


def sign(message: bytes) -> bytes:
    """Sign a message with the local identity.

    Args:
        message: Bytes to sign

    Returns:
        64-byte Ed25519 signature
    """
    signing_key = get_signing_key()
    signed = signing_key.sign(message, encoder=RawEncoder)
    return signed.signature


def verify(message: bytes, signature: bytes, did: str) -> bool:
    """Verify a signature against a DID.

    Args:
        message: Original message bytes
        signature: 64-byte Ed25519 signature
        did: did:key of the signer

    Returns:
        True if signature is valid
    """
    try:
        public_bytes = _decode_did_key(did)
        verify_key = VerifyKey(public_bytes)
        verify_key.verify(message, signature)
        return True
    except (BadSignatureError, ValueError):
        return False
