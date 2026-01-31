"""Post schema, signing, and verification for dagit messages."""

import base64
import json
from datetime import datetime, timezone
from typing import Any

from . import identity, ipfs

MESSAGE_VERSION = 1


def create_post(
    content: str,
    reply_to: str | None = None,
    post_type: str = "post",
) -> dict:
    """Create an unsigned post message.

    Args:
        content: Post content text
        reply_to: CID of post being replied to (optional)
        post_type: Message type (default "post")

    Returns:
        Unsigned post dict
    """
    ident = identity.load()
    if not ident:
        raise RuntimeError("No identity found. Run 'dagit init' first.")

    return {
        "v": MESSAGE_VERSION,
        "type": post_type,
        "content": content,
        "author": ident["did"],
        "reply_to": reply_to,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _signing_payload(post: dict) -> bytes:
    """Create the canonical signing payload for a post.

    Excludes the signature field and uses deterministic JSON encoding.
    """
    # Create a copy without signature for signing
    signing_dict = {k: v for k, v in post.items() if k != "signature"}
    # Deterministic JSON: sorted keys, no whitespace
    return json.dumps(signing_dict, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sign_post(post: dict) -> dict:
    """Sign a post with the local identity.

    Args:
        post: Unsigned post dict

    Returns:
        Post dict with 'signature' field added
    """
    payload = _signing_payload(post)
    signature = identity.sign(payload)
    return {**post, "signature": base64.b64encode(signature).decode("ascii")}


def verify_post(post: dict) -> bool:
    """Verify a post's signature.

    Args:
        post: Post dict with 'signature' field

    Returns:
        True if signature is valid
    """
    if "signature" not in post:
        return False

    try:
        signature = base64.b64decode(post["signature"])
        payload = _signing_payload(post)
        return identity.verify(payload, signature, post["author"])
    except (KeyError, ValueError):
        return False


def serialize(post: dict) -> str:
    """Serialize a post to JSON string.

    Args:
        post: Post dict

    Returns:
        JSON string (compact format for IPFS)
    """
    return json.dumps(post, separators=(",", ":"))


def deserialize(data: str | bytes) -> dict:
    """Deserialize a post from JSON.

    Args:
        data: JSON string or bytes

    Returns:
        Post dict
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)


def publish(content: str, reply_to: str | None = None) -> str:
    """Create, sign, and publish a post to IPFS.

    Args:
        content: Post content text
        reply_to: CID of post being replied to (optional)

    Returns:
        CID of the published post
    """
    post = create_post(content, reply_to=reply_to)
    signed = sign_post(post)
    cid = ipfs.add(signed)
    ipfs.pin(cid)
    return cid


def fetch(cid: str) -> tuple[dict, bool]:
    """Fetch a post from IPFS and verify its signature.

    Args:
        cid: Content identifier of the post

    Returns:
        Tuple of (post dict, is_verified)
    """
    data = ipfs.get(cid)
    post = deserialize(data)
    verified = verify_post(post)
    return post, verified
