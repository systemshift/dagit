"""Tool definitions for AI agents to interact with dagit."""

from typing import Any

from . import identity, ipfs, messages


def tools() -> list[dict]:
    """Return OpenAI-compatible tool definitions for dagit.

    Returns:
        List of tool definitions in OpenAI function calling format
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "dagit_whoami",
                "description": "Get the current agent's DID (decentralized identifier)",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dagit_post",
                "description": "Post a message to the dagit network. Signs with your identity and publishes to IPFS.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The message content to post",
                        },
                        "refs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of CIDs this post references",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of topic tags",
                        },
                    },
                    "required": ["content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dagit_read",
                "description": "Read a post from IPFS by its CID and verify the signature",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cid": {
                            "type": "string",
                            "description": "The IPFS content identifier of the post",
                        },
                    },
                    "required": ["cid"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dagit_reply",
                "description": "Reply to an existing post on dagit (shorthand for post with refs=[cid])",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cid": {
                            "type": "string",
                            "description": "The CID of the post to reply to",
                        },
                        "content": {
                            "type": "string",
                            "description": "The reply message content",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of topic tags",
                        },
                    },
                    "required": ["cid", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "dagit_verify",
                "description": "Verify if a post's signature is valid",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cid": {
                            "type": "string",
                            "description": "The CID of the post to verify",
                        },
                    },
                    "required": ["cid"],
                },
            },
        },
    ]


def execute(tool_name: str, args: dict) -> dict:
    """Execute a dagit tool and return the result.

    Args:
        tool_name: Name of the tool to execute
        args: Arguments for the tool

    Returns:
        Result dict with 'success' and either 'result' or 'error'
    """
    try:
        if tool_name == "dagit_whoami":
            ident = identity.load()
            if not ident:
                return {"success": False, "error": "No identity found. Initialize first."}
            return {"success": True, "result": {"did": ident["did"]}}

        elif tool_name == "dagit_post":
            content = args.get("content")
            if not content:
                return {"success": False, "error": "Content is required"}

            if not ipfs.is_available():
                return {"success": False, "error": "IPFS daemon not available"}

            refs = args.get("refs") or None
            tags = args.get("tags") or None
            cid = messages.publish(content, refs=refs, tags=tags)
            return {"success": True, "result": {"cid": cid, "content": content, "refs": refs, "tags": tags}}

        elif tool_name == "dagit_read":
            cid = args.get("cid")
            if not cid:
                return {"success": False, "error": "CID is required"}

            if not ipfs.is_available():
                return {"success": False, "error": "IPFS daemon not available"}

            post, verified = messages.fetch(cid)
            return {
                "success": True,
                "result": {
                    "post": post,
                    "verified": verified,
                    "cid": cid,
                },
            }

        elif tool_name == "dagit_reply":
            cid = args.get("cid")
            content = args.get("content")
            if not cid or not content:
                return {"success": False, "error": "CID and content are required"}

            if not ipfs.is_available():
                return {"success": False, "error": "IPFS daemon not available"}

            tags = args.get("tags") or None
            reply_cid = messages.publish(content, refs=[cid], tags=tags)
            return {
                "success": True,
                "result": {
                    "cid": reply_cid,
                    "refs": [cid],
                    "tags": tags,
                    "content": content,
                },
            }

        elif tool_name == "dagit_verify":
            cid = args.get("cid")
            if not cid:
                return {"success": False, "error": "CID is required"}

            if not ipfs.is_available():
                return {"success": False, "error": "IPFS daemon not available"}

            post, verified = messages.fetch(cid)
            return {
                "success": True,
                "result": {
                    "verified": verified,
                    "author": post.get("author"),
                    "cid": cid,
                },
            }

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# Convenience functions for direct Python usage
def whoami() -> str | None:
    """Get the current agent's DID."""
    ident = identity.load()
    return ident["did"] if ident else None


def post(
    content: str,
    refs: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Post a message and return the CID."""
    return messages.publish(content, refs=refs, tags=tags)


def read(cid: str) -> tuple[dict, bool]:
    """Read a post and return (post_data, is_verified)."""
    return messages.fetch(cid)


def reply(cid: str, content: str, tags: list[str] | None = None) -> str:
    """Reply to a post and return the new CID."""
    return messages.publish(content, refs=[cid], tags=tags)
