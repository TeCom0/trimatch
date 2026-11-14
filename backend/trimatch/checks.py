"""Result type shared by validation, matching and decision."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Check:
    code: str  # reason code, e.g. "QTY_EXCEEDS_RECEIVED"
    ok: bool
    detail: str = ""
    doc: str = ""  # "invoice" | "bl" | "" (both / order level)
    line: int | None = None  # 0-based line index on that document

    def to_dict(self) -> dict:
        return asdict(self)


def failed(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok]
