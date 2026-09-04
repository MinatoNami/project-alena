"""External research: ingesting it, and turning it into observations."""

from .ingest import IngestResult, ingest_file, ingest_text, research_files
from .propose import ProposalResult, propose
from .parse import ParsedObservation, ParsedResearch, normalize_title, parse_research

__all__ = [
    "IngestResult",
    "ProposalResult",
    "ParsedObservation",
    "ParsedResearch",
    "ingest_file",
    "ingest_text",
    "normalize_title",
    "parse_research",
    "propose",
    "research_files",
]
