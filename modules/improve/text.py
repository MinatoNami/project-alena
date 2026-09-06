"""Text comparison helpers.

Lives on its own because both the research parser and the de-duplicator need
it, and having either own it makes the two import each other in a cycle.
"""

from __future__ import annotations

import re

_NON_WORD = re.compile(r"[^a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "become", "becomes", "by",
        "can", "could", "for", "from", "has", "have", "in", "into", "is", "it",
        "its", "may", "of", "on", "or", "our", "should", "that", "the", "this",
        "to", "we", "with", "would",
    }
)


def words(text: str) -> list:
    return [w for w in _NON_WORD.sub(" ", (text or "").lower()).split() if w]


def meaningful_words(text: str) -> list:
    found = words(text)
    # Falling back to the raw words matters for a title that is *all*
    # stopwords: dropping everything would make it match every other such
    # title exactly.
    return [w for w in found if w not in STOPWORDS] or found


def normalize_title(title: str) -> str:
    """A comparable form of a title.

    Lowercased, punctuation dropped, stopwords removed, words sorted. Sorting
    is what makes "Semantic search for the library" and "Library semantic
    search" the same string -- a reworded duplicate is the case dedup exists
    to catch.
    """
    return " ".join(sorted(meaningful_words(title)))


def tokens(text: str) -> set:
    return set(meaningful_words(text))


def jaccard(a: str, b: str) -> float:
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# How a status reads when something already sitting at it comes round again.
# Phrased as what is outstanding, because that is what the reader has to act
# on: "rejected" is a fact about the past, "already rejected" is a reason not
# to spend the next hour on it.
#
# Shared rather than duplicated: the de-duplicator says this to the operator
# and the reviewer prompt says it to an agent, and the two disagreeing about
# what "accepted" means is how a duplicate gets waved through.
WHERE_IT_STANDS = {
    "awaiting review": "already proposed and awaiting review",
    "recommended": "already proposed and awaiting your decision",
    "accepted": "already accepted and awaiting implementation",
    "implemented": "already implemented, and the outcome is not yet recorded",
    "rejected": "already rejected",
    "abandoned": "already proposed and then abandoned",
    "successful": "already implemented, and it worked",
    "unsuccessful": "already implemented, and it did not work",
}


def where_it_stands(status: str) -> str:
    return WHERE_IT_STANDS.get(status, f"already proposed ({status})")


# --- citations -------------------------------------------------------------
#
# Reserved by RFC 2606 and RFC 6761 precisely so that nobody can register them:
# a URL on one of these cannot resolve to a source, ever. Anything citing one
# is either a template nobody filled in or a fabrication.
_RESERVED_HOSTS = ("example.com", "example.net", "example.org", "localhost")
_RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
# Templates people leave behind. Narrower and more literal than the reserved
# list on purpose -- a real page can be called anything, and guessing at
# "looks fake" would start rejecting genuine sources.
_PLACEHOLDER_MARKERS = ("your-domain", "yourdomain", "example.url", "<url>", "todo", "tbd")

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def unverifiable_citations(evidence: str | None) -> list[str]:
    """URLs in `evidence` that cannot lead to a source, in the order cited.

    Not a judgement about the claim. A real finding can arrive with a citation
    somebody templated and never filled in; the point is that the reviewer
    should not read such a URL as support, and until now nothing said so.

    ALENA's own research backlog carried four of these --
    `https://example.com/nuxt-release-policy` and three more on a single
    observation -- through ingest and a full Codex review without comment. The
    second reviewer noticed on the first day it ran.
    """
    found = []
    for url in _URL.findall(evidence or ""):
        lowered = url.lower()
        host = lowered.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
        if (
            host in _RESERVED_HOSTS
            or any(host.endswith(f".{h}") for h in _RESERVED_HOSTS)
            or any(host.endswith(s) for s in _RESERVED_SUFFIXES)
            or any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
        ):
            found.append(url)
    return found
