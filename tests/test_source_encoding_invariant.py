"""Every text-mode ``open()`` in src/ must name its encoding.

Without an explicit ``encoding=``, ``open()`` uses the platform default:
UTF-8 on Linux/macOS, but the ANSI codepage (cp1252 on a US/Western install)
on Windows. Today that is only a latent hazard here -- the index and topics
writers pass ``json.dump(..., indent=2)``, whose default ``ensure_ascii=True``
escapes non-ASCII to ``\\uXXXX``, so the bytes on disk are pure ASCII and
survive either codec.

The trap is that the conversation files themselves are written with
``ensure_ascii=False`` through ``aiofiles.open(..., encoding="utf-8")``, so
making the index writers match "for consistency" is an obvious future
tidy-up -- and on Windows it would immediately write an index the reader
cannot decode. That is the same class as #190-#196: two stores that agree in
the aggregate while disagreeing in fact, here about which codec they speak.

This is a source-level invariant rather than a behavioural test on purpose:
the defect is invisible on the platform CI runs its coverage on, so only
reading the source catches a reintroduction.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# Text-mode open() calls only. Binary mode ("rb"/"wb"/"ab") takes no encoding,
# and sqlite3.connect / aiofiles are separate APIs with their own handling.
_OPEN_CALL = re.compile(r"(?<![.\w])open\(([^)]*)\)")


def _encodingless_open_calls(source: str) -> list[str]:
    found = []
    for match in _OPEN_CALL.finditer(source):
        args = match.group(1)
        if "encoding=" in args:
            continue
        if re.search(r"""["'][rwax+]*b[rwax+]*["']""", args):
            continue  # binary mode: encoding= would be a TypeError
        found.append(match.group(0))
    return found


def test_no_text_mode_open_without_explicit_encoding():
    offenders = {}
    for path in sorted(SRC.rglob("*.py")):
        calls = _encodingless_open_calls(path.read_text(encoding="utf-8"))
        if calls:
            offenders[str(path.relative_to(SRC))] = calls

    assert not offenders, (
        "text-mode open() without encoding= in src/ -- these read as UTF-8 on "
        f"Linux and cp1252 on Windows: {offenders}"
    )
