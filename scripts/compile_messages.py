#!/usr/bin/env python
"""Compile locale/*.po to .mo without requiring system gettext/msgfmt."""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def _encode_mo(messages: dict[str, str]) -> bytes:
    # GNU gettext binary MO format (little-endian)
    keys = sorted(messages.keys())
    ids = b"\x00".join(k.encode("utf-8") for k in keys) + b"\x00"
    strs = b"\x00".join(messages[k].encode("utf-8") for k in keys) + b"\x00"

    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    offset = 0
    for k in keys:
        raw = k.encode("utf-8")
        koffsets.append((len(raw), keystart + offset))
        offset += len(raw) + 1
    offset = 0
    for k in keys:
        raw = messages[k].encode("utf-8")
        voffsets.append((len(raw), valuestart + offset))
        offset += len(raw) + 1

    output = [
        struct.pack(
            "Iiiiiii",
            0x950412DE,  # magic
            0,  # revision
            len(keys),
            7 * 4,  # offset of key table
            7 * 4 + 8 * len(keys),  # offset of value table
            0,
            0,
        )
    ]
    for length, off in koffsets:
        output.append(struct.pack("ii", length, off))
    for length, off in voffsets:
        output.append(struct.pack("ii", length, off))
    output.append(ids)
    output.append(strs)
    return b"".join(output)


def parse_po(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    msgid = None
    msgstr = None
    mode = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if msgid is not None and msgstr is not None and msgid != "":
                messages[msgid] = msgstr
            msgid = line[6:].strip().strip('"')
            msgstr = None
            mode = "id"
        elif line.startswith("msgstr "):
            msgstr = line[7:].strip().strip('"')
            mode = "str"
        elif line.startswith('"') and mode == "id" and msgid is not None:
            msgid += line.strip().strip('"')
        elif line.startswith('"') and mode == "str" and msgstr is not None:
            msgstr += line.strip().strip('"')
    if msgid is not None and msgstr is not None and msgid != "":
        messages[msgid] = msgstr
    return messages


def compile_locales(root: Path) -> int:
    locale_root = root / "locale"
    count = 0
    for po in locale_root.glob("*/LC_MESSAGES/django.po"):
        messages = parse_po(po)
        # Required so Python/Django gettext decodes non-ASCII as UTF-8.
        messages[""] = (
            "Content-Type: text/plain; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n"
        )
        mo = po.with_suffix(".mo")
        mo.write_bytes(_encode_mo(messages))
        print(f"compiled {po.relative_to(root)} -> {len(messages) - 1} strings")
        count += 1
    return count


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[1]
    n = compile_locales(base)
    if n == 0:
        print("No .po files found", file=sys.stderr)
        sys.exit(1)
