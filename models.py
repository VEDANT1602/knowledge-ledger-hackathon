from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Source:
    url: str
    snapshot_id: Optional[str] = None
    quote: Optional[str] = None


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    confident: bool = True
    conflict_note: Optional[str] = None


@dataclass
class Conflict:
    topic: str
    values: list[str]
    sources: list[Source]
    resolution: Optional[str] = None
    reason: Optional[str] = None


try:
    from contract import Answer, Conflict, Source
except ImportError:
    pass
