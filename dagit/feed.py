"""IPNS-based feed publishing and following for dagit.

No dagit-server needed -- pure IPFS.
"""

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from . import identity, ipfs, messages

logger = logging.getLogger(__name__)

DAGIT_DIR = Path.home() / ".dagit"
FOLLOWING_FILE = DAGIT_DIR / "following.json"
FEED_FILE = DAGIT_DIR / "feed.json"
KEY_NAME = "dagit-did"
MAX_FEED_ENTRIES = 100

# --- Petname generator (deterministic adjective-noun from DID) ---

_ADJECTIVES = [
    "amber", "azure", "bold", "bright", "calm", "clear", "cool", "coral",
    "crimson", "dark", "deep", "dry", "dusk", "faint", "fast", "firm",
    "gold", "green", "grey", "haze", "iron", "keen", "kind", "late",
    "light", "live", "long", "loud", "low", "mild", "mint", "mist",
    "moss", "near", "new", "next", "north", "odd", "old", "open",
    "pale", "pine", "plain", "proud", "pure", "quick", "quiet", "rare",
    "raw", "red", "rich", "sage", "salt", "sand", "sharp", "shy",
    "silk", "slim", "slow", "soft", "south", "steel", "still", "stone",
]

_NOUNS = [
    "ash", "bay", "birch", "bloom", "brook", "cave", "cedar", "cliff",
    "cloud", "coal", "cove", "crane", "creek", "crow", "dawn", "deer",
    "dove", "dune", "dusk", "eagle", "elm", "ember", "fern", "finch",
    "fire", "flint", "fox", "frost", "gale", "glen", "grove", "hawk",
    "haze", "heath", "heron", "hill", "ivy", "jade", "jay", "lake",
    "lark", "leaf", "marsh", "mesa", "moon", "oak", "owl", "peak",
    "pine", "pond", "rain", "reed", "ridge", "rock", "rose", "sage",
    "shade", "shore", "sky", "snow", "star", "storm", "stone", "vale",
]


def petname_from_did(did: str) -> str:
    """Generate a deterministic adjective-noun name from a DID."""
    h = hashlib.sha256(did.encode()).digest()
    adj = _ADJECTIVES[h[0] % len(_ADJECTIVES)]
    noun = _NOUNS[h[1] % len(_NOUNS)]
    return f"{adj}-{noun}"


# --- Base36 encoder (no deps) ---

BASE36_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36_encode(data: bytes) -> str:
    """Encode bytes as base36 string."""
    num = int.from_bytes(data, "big")
    if num == 0:
        return "0"
    chars = []
    while num > 0:
        chars.append(BASE36_CHARS[num % 36])
        num //= 36
    return "".join(reversed(chars))


# --- Key import into Kubo ---

_key_imported = False


def ensure_dagit_key() -> None:
    """Import dagit Ed25519 key into Kubo keystore if not already present."""
    global _key_imported
    if _key_imported:
        return

    keys = ipfs.key_list()
    if any(k["Name"] == KEY_NAME for k in keys):
        _key_imported = True
        return

    ident = identity.load()
    if not ident:
        raise RuntimeError("No dagit identity found")

    seed = base64.b64decode(ident["private_key"])  # 32-byte Ed25519 seed

    # PKCS8 DER for Ed25519 private key: fixed 16-byte prefix + 32-byte seed
    der_prefix = bytes([
        0x30, 0x2E, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06,
        0x03, 0x2B, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
    ])
    der = der_prefix + seed
    b64 = base64.b64encode(der).decode("ascii")

    # Wrap in PEM lines (64 chars per line)
    lines = [b64[i:i + 64] for i in range(0, len(b64), 64)]
    pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"

    ipfs.key_import(KEY_NAME, pem)
    _key_imported = True


# --- DID -> IPNS name ---

def did_to_ipns_name(did: str) -> str:
    """Derive IPNS name from a DID (for resolving anyone's feed).

    Steps:
    1. Extract 32-byte pubkey from DID
    2. Build libp2p protobuf PublicKey (4-byte prefix + pubkey)
    3. Identity multihash (2-byte prefix + protobuf)
    4. CIDv1 (2-byte prefix + multihash)
    5. Base36-encode with 'k' multibase prefix
    """
    pubkey = identity._decode_did_key(did)  # 32 bytes

    # libp2p protobuf PublicKey: type=Ed25519(1), data=pubkey
    # 0x08 0x01 = field 1, varint 1 (KeyType = Ed25519)
    # 0x12 0x20 = field 2, length 32 (Data)
    protobuf = b"\x08\x01\x12\x20" + pubkey

    # Identity multihash: 0x00 (identity) 0x24 (length=36)
    multihash = b"\x00" + bytes([len(protobuf)]) + protobuf

    # CIDv1: 0x01 (version) 0x72 (libp2p-key codec)
    cid_bytes = b"\x01\x72" + multihash

    # Base36 with 'k' multibase prefix
    return "k" + _base36_encode(cid_bytes)


# --- Following list ---

def _load_json(path: Path, default):
    """Load JSON file or return default."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data) -> None:
    """Save data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_following() -> list[dict]:
    """Load following list. Normalizes old string-only entries to dicts."""
    raw = _load_json(FOLLOWING_FILE, [])
    entries = []
    for item in raw:
        if isinstance(item, str):
            entries.append({"did": item, "addedAt": "", "lastSeenCids": []})
        elif isinstance(item, dict):
            item.setdefault("addedAt", "")
            item.setdefault("lastSeenCids", [])
            entries.append(item)
    return entries


def save_following(entries: list[dict]) -> None:
    """Save following list."""
    _save_json(FOLLOWING_FILE, entries)


def has_following() -> bool:
    """Quick check if following file exists and is non-empty."""
    if not FOLLOWING_FILE.exists():
        return False
    try:
        data = json.loads(FOLLOWING_FILE.read_text())
        return bool(data)
    except (json.JSONDecodeError, OSError):
        return False


def follow(did: str, alias: str | None = None) -> str:
    """Follow a DID. Returns status message."""
    if not did.startswith("did:key:z"):
        return "Error: invalid DID format"

    entries = load_following()
    if any(e["did"] == did for e in entries):
        return f"Already following {did}"

    if alias is None:
        alias = petname_from_did(did)
    entries.append({
        "did": did,
        "alias": alias,
        "addedAt": datetime.now(timezone.utc).isoformat(),
        "lastSeenCids": [],
    })
    save_following(entries)
    return f"Now following {alias} ({did[-12:]})"


def unfollow(did: str) -> str:
    """Unfollow a DID. Returns status message."""
    entries = load_following()
    for i, e in enumerate(entries):
        if e["did"] == did:
            removed = entries.pop(i)
            save_following(entries)
            return f"Unfollowed {removed.get('alias') or did}"
    return f"Not following {did}"


def list_following() -> str:
    """Return formatted following list."""
    entries = load_following()
    if not entries:
        return "Not following anyone."

    lines = [f"Following {len(entries)} feed(s):"]
    for e in entries:
        label = f"{e['alias']} ({e['did'][-12:]})" if e.get("alias") else e["did"]
        n = len(e.get("lastSeenCids", []))
        lines.append(f"  {label} -- {n} known posts")
    return "\n".join(lines)


# --- Own feed index ---

def _load_feed_index() -> dict | None:
    """Load our own published feed index."""
    return _load_json(FEED_FILE, None)


def _save_feed_index(index: dict) -> None:
    """Save our own feed index."""
    _save_json(FEED_FILE, index)


def publish_feed(new_post_cid: str) -> None:
    """Update feed index with new post, add to IPFS, publish via IPNS.

    The IPNS publish (DHT) is slow, so we fire it in a background thread.
    The local feed file is saved immediately.
    """
    ident = identity.load()
    if not ident:
        return

    feed = _load_feed_index()
    if feed is None:
        feed = {"author": ident["did"], "posts": []}

    # Prepend new post, cap at MAX_FEED_ENTRIES
    feed["posts"].insert(0, {
        "cid": new_post_cid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    feed["posts"] = feed["posts"][:MAX_FEED_ENTRIES]

    # Save locally immediately
    _save_feed_index(feed)

    # Add to IPFS and publish via IPNS (background, don't block)
    try:
        feed_cid = ipfs.add(feed)

        def _bg_publish():
            try:
                ipfs.name_publish(feed_cid, KEY_NAME)
            except Exception as e:
                logger.debug(f"IPNS publish failed: {e}")

        Thread(target=_bg_publish, daemon=True).start()
    except Exception as e:
        logger.debug(f"Feed IPFS add failed: {e}")


# --- Check followed feeds ---

def check_feeds() -> str:
    """Resolve all followed feeds via IPNS, fetch new posts, verify, return summary."""
    entries = load_following()
    if not entries:
        return "Not following anyone."

    lines = []
    for entry in entries:
        did = entry["did"]
        alias = entry.get("alias")
        label = alias or did[-12:]

        try:
            ipns_name = did_to_ipns_name(did)
            feed_cid = ipfs.name_resolve(ipns_name, timeout_s=30)
            feed_data = ipfs.get_json(feed_cid)

            posts = feed_data.get("posts", [])
            if not posts:
                lines.append(f"{label}: empty feed")
                continue

            known = set(entry.get("lastSeenCids", []))
            new_posts = [p for p in posts if p["cid"] not in known]

            ingested = 0
            for p in new_posts:
                try:
                    post, verified = messages.fetch(p["cid"])
                    if post.get("author") != did:
                        continue
                    if not verified:
                        continue
                    ingested += 1
                except Exception:
                    pass

            # Update last seen CIDs
            entry["lastSeenCids"] = [p["cid"] for p in posts]

            if ingested > 0:
                lines.append(f"{label}: {ingested} new post(s)")
            else:
                lines.append(f"{label}: up to date")

        except Exception as e:
            lines.append(f"{label}: failed ({e})")

    save_following(entries)
    return "\n".join(lines) if lines else "All feeds checked."
