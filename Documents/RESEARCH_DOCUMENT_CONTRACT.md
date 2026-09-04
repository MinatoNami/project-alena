# Research Document Contract

What ALENA expects a research document to look like, and what it does with it.

ALENA cannot trigger ChatGPT Work — that is a provider-side scheduler. The
integration is therefore a file contract: the scheduled task produces a
markdown document, and ALENA ingests it.

```bash
alena-improve ingest-research luma-index research/luma-index/2026-09-03.md
alena-improve ingest-research luma-index --from-dir ~/Downloads/alena-research
```

## The shape

`config/research-template.md` is the copy to hand to the scheduled task.

```markdown
# Research: luma-index

Repository: luma-index
Date: 2026-09-03
Source: chatgpt-work

## A short, specific title

What changed outside the repository, and why it could matter here.
One claim per heading.

Evidence: https://example.com/one https://example.com/two
```

| Element | Meaning |
|---|---|
| `Repository:` | Must match the repository being ingested, or the document is refused |
| `Date:`, `Source:` | Recorded with the document |
| `## Heading` | One observation. The heading becomes its title |
| `Evidence:` | Citations. Counted — an uncited observation scores zero on evidence |

Both `**Evidence:** x` and `**Evidence**: x` parse. A heading with nothing
under it is treated as a table-of-contents entry and skipped.

Parsing degrades rather than failing: a document with no headings becomes a
single observation containing the whole text. A report in the wrong shape is
still worth reading.

## Ask for observations, not recommendations

The research prompt should say so explicitly. Research that arrives already
committed to an implementation biases the engineering review that is supposed
to decide whether the idea fits the actual codebase.

## What happens on ingest

```
document ──► observations ──► dedup ──► review ──► score ──► report
                                │
                          already proposed
                                │
                             skipped
```

De-duplication runs at ingest rather than after review, because reviewing a
proposal that was already turned down is the expensive half of the mistake.
It compares against both decided recommendations and observations still
waiting for review.

Re-ingesting the same file is a no-op — a watched drop directory will hand
ALENA the same document more than once.

## Research text is untrusted

This is the part worth understanding before pointing ALENA at a research feed.

The document is written by an external agent reading the public internet, and
it ends up in front of a coding agent. That is a prompt-injection path. Three
things hold it closed, in descending order of how much they matter:

**The gateway.** The review runs as agent `codex`, and the tool policy grants
that identity read-only tools. `codex_edit` and `codex_refactor` are not on its
list, so a fully hijacked review still cannot write. This is enforcement, not
persuasion — it does not depend on the model behaving.

**`repo_path` comes from the registry.** Never from the document. A document
asking for a different path does not get one.

**Framing.** The observation is wrapped in a delimiter it cannot contain, the
instruction to ignore instructions comes *before* the data, and the observation
is labelled as third-party text carrying no authority.

No attempt is made to detect injection phrasing. That is whack-a-mole and it
fails quietly; the containment above is what actually holds.

An injection attempt is ingested like any other observation, reviewed, and
rejected on its merits — after which it is recorded as rejected, so the same
attempt is recognised the next time it arrives.
