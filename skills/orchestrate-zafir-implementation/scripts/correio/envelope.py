"""Correio v2 envelope: a strict YAML-subset frontmatter plus a Markdown body.

The CLI writes every envelope; agents never type one. The subset is exactly what ``emit`` produces:

    ---
    correio: 2
    id: <uuid>
    ...
    fields:
      key: scalar
    attachments:
      - path: "/abs/path"
        sha256: <hex>
        bytes: 12
    ---
    <body>

Scalars are ``null``, ``true``, ``false``, decimal integers, plain strings and double-quoted (JSON) strings.
``fields`` is a one-level map of scalars, ``attachments`` a list of {path, sha256, bytes} maps, and
``{}``/``[]`` mark them empty. ``parse`` accepts only canonical bytes: it re-emits what it read and refuses
any difference, so the sha256 of a stored envelope is stable and every envelope has one spelling.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

MAX_ENVELOPE_BYTES = 1024 * 1024
CORREIO = 2
# Fixed key order of the header; ``fields`` and ``attachments`` close it.
HEADER_KEYS = ("correio", "id", "space", "protocol", "version", "thread", "type", "from", "from_generation",
               "to", "in_reply_to", "sent_at", "subject")
FIELD_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
ATTACHMENT_KEYS = ("path", "sha256", "bytes")
INT = re.compile(r"^(0|-?[1-9][0-9]{0,18})$")
PLAIN = re.compile(r"^[A-Za-z0-9_./@+-][A-Za-z0-9_./@+:-]*$")
RESERVED_WORDS = {"null", "true", "false", "~", "yes", "no", "on", "off", "y", "n", "nan", "inf"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class EnvelopeError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise EnvelopeError(f"not a scalar: {type(value).__name__}")
    if "\x00" in value:
        raise EnvelopeError("strings may not contain NUL")
    if (PLAIN.match(value) and value.lower() not in RESERVED_WORDS and not INT.match(value)
            and not value.startswith("-") and value != "---"):
        return value
    return json.dumps(value, ensure_ascii=False)


def _read_scalar(token: str) -> Any:
    if token == "null":
        return None
    if token == "true":
        return True
    if token == "false":
        return False
    if INT.match(token):
        return int(token)
    if token.startswith('"'):
        try:
            value = json.loads(token)
        except json.JSONDecodeError as exc:
            raise EnvelopeError(f"bad quoted string: {token[:40]!r}") from exc
        if not isinstance(value, str):
            raise EnvelopeError("a quoted token must be a string")
        return value
    if PLAIN.match(token) and token.lower() not in RESERVED_WORDS:
        return token
    raise EnvelopeError(f"value outside the YAML subset: {token[:40]!r}")


def emit(header: dict[str, Any], fields: dict[str, Any], attachments: list[dict[str, Any]], body: str) -> bytes:
    """Canonical envelope bytes. ``header`` holds exactly HEADER_KEYS."""
    if set(header) != set(HEADER_KEYS):
        raise EnvelopeError(f"header keys must be exactly {HEADER_KEYS}")
    if not isinstance(body, str) or "\x00" in body:
        raise EnvelopeError("body must be text without NUL")
    lines = ["---"]
    for key in HEADER_KEYS:
        lines.append(f"{key}: {_scalar(header[key])}")
    if fields:
        lines.append("fields:")
        for key in sorted(fields):
            if not isinstance(key, str) or not FIELD_KEY.match(key):
                raise EnvelopeError(f"invalid field name: {key!r}")
            lines.append(f"  {key}: {_scalar(fields[key])}")
    else:
        lines.append("fields: {}")
    if attachments:
        lines.append("attachments:")
        for item in sorted(attachments, key=lambda a: str(a.get("path"))):
            if set(item) != set(ATTACHMENT_KEYS):
                raise EnvelopeError(f"an attachment holds exactly {ATTACHMENT_KEYS}")
            if not isinstance(item["path"], str) or not item["path"].startswith("/"):
                raise EnvelopeError("attachment path must be absolute")
            if not isinstance(item["sha256"], str) or not SHA256.match(item["sha256"]):
                raise EnvelopeError("attachment sha256 must be 64 lowercase hex")
            if type(item["bytes"]) is not int or item["bytes"] < 0:
                raise EnvelopeError("attachment bytes must be a non-negative integer")
            lines.append(f"  - path: {_scalar(item['path'])}")
            lines.append(f"    sha256: {item['sha256']}")
            lines.append(f"    bytes: {item['bytes']}")
    else:
        lines.append("attachments: []")
    lines.append("---")
    text = "\n".join(lines) + "\n" + body
    if not text.endswith("\n"):
        text += "\n"
    data = text.encode("utf-8")
    if len(data) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError(f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes; send the body as an attachment")
    return data


def _split(line: str, where: str) -> tuple[str, str]:
    key, sep, rest = line.partition(": ")
    if not sep or not key or key != key.strip() or rest != rest.strip() or not rest:
        raise EnvelopeError(f"bad {where} line: {line[:60]!r}")
    return key, rest


def parse(data: bytes) -> dict[str, Any]:
    """Parse canonical envelope bytes into a dict (header keys, ``fields``, ``attachments``, ``body``)."""
    if not isinstance(data, (bytes, bytearray)):
        raise EnvelopeError("envelope must be bytes")
    if len(data) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError(f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EnvelopeError("envelope is not UTF-8") from exc
    if "\r" in text.split("\n---\n", 1)[0] or "\x00" in text:
        raise EnvelopeError("envelope header has CR or NUL")
    if not text.startswith("---\n"):
        raise EnvelopeError("envelope must start with ---")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise EnvelopeError("envelope header is not closed by ---")
    header_lines = text[4:end].split("\n")
    body = text[end + 5:]
    header: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    attachments: list[dict[str, Any]] = []
    i = 0
    for key in HEADER_KEYS:
        if i >= len(header_lines):
            raise EnvelopeError(f"missing header key: {key}")
        k, v = _split(header_lines[i], "header")
        if k != key:
            raise EnvelopeError(f"expected {key}, found {k}")
        header[key] = _read_scalar(v)
        i += 1
    if i >= len(header_lines):
        raise EnvelopeError("missing fields")
    if header_lines[i] == "fields: {}":
        i += 1
    elif header_lines[i] == "fields:":
        i += 1
        while i < len(header_lines) and header_lines[i].startswith("  ") and not header_lines[i].startswith("  - "):
            k, v = _split(header_lines[i][2:], "field")
            if not FIELD_KEY.match(k) or k in fields:
                raise EnvelopeError(f"invalid or repeated field: {k!r}")
            fields[k] = _read_scalar(v)
            i += 1
        if not fields:
            raise EnvelopeError("empty fields map must be written {}")
    else:
        raise EnvelopeError("expected fields")
    if i >= len(header_lines):
        raise EnvelopeError("missing attachments")
    if header_lines[i] == "attachments: []":
        i += 1
    elif header_lines[i] == "attachments:":
        i += 1
        while i < len(header_lines) and header_lines[i].startswith("  - "):
            item: dict[str, Any] = {}
            k, v = _split(header_lines[i][4:], "attachment")
            item[k] = _read_scalar(v)
            i += 1
            while i < len(header_lines) and header_lines[i].startswith("    "):
                k, v = _split(header_lines[i][4:], "attachment")
                if k in item:
                    raise EnvelopeError(f"repeated attachment key: {k}")
                item[k] = _read_scalar(v)
                i += 1
            attachments.append(item)
        if not attachments:
            raise EnvelopeError("empty attachments list must be written []")
    else:
        raise EnvelopeError("expected attachments")
    if i != len(header_lines):
        raise EnvelopeError(f"unexpected header line: {header_lines[i][:60]!r}")
    value = {**header, "fields": fields, "attachments": attachments, "body": body}
    validate_shape(value)
    if emit(header, fields, attachments, body) != bytes(data):
        raise EnvelopeError("envelope is not in canonical form")
    return value


def validate_shape(value: dict[str, Any]) -> None:
    """Protocol-independent checks every envelope passes."""
    if value.get("correio") != CORREIO:
        raise EnvelopeError("correio must be 2")
    try:
        if str(uuid.UUID(str(value.get("id")))) != value.get("id"):
            raise ValueError
    except ValueError as exc:
        raise EnvelopeError("id must be a canonical lowercase UUID") from exc
    for key in ("space", "protocol", "version", "thread", "type", "from", "to", "sent_at", "subject"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise EnvelopeError(f"{key} must be a nonempty string")
    for key in ("from", "to"):
        if not NAME.match(value[key]):
            raise EnvelopeError(f"{key} is not a valid agent name: {value[key]!r}")
    generation = value.get("from_generation")
    if generation is not None and (type(generation) is not int or generation < 1):
        raise EnvelopeError("from_generation must be null or a positive integer")
    reply = value.get("in_reply_to")
    if reply is not None:
        try:
            if str(uuid.UUID(str(reply))) != reply:
                raise ValueError
        except ValueError as exc:
            raise EnvelopeError("in_reply_to must be null or a canonical UUID") from exc
    if len(value["subject"]) > 300 or "\n" in value["subject"]:
        raise EnvelopeError("subject must be one line of at most 300 characters")
    if len(value["sent_at"]) > 64:
        raise EnvelopeError("sent_at must be a short timestamp")
    for item in value.get("attachments", []):
        if set(item) != set(ATTACHMENT_KEYS):
            raise EnvelopeError(f"an attachment holds exactly {ATTACHMENT_KEYS}")
