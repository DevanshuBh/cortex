# ADR 0002 — Structure-aware chunks sized in the embedding model's own tokens

Status: accepted · 2026-11-14

## Context
Chunks sized in characters or words silently exceed the embedding model's input limit, and the model truncates
the end of the chunk without warning — a hidden recall bug (guide correction for steps 1.3/1.4).

## Decision
- Split by headings first (chunks never cross a section), then paragraphs, then sentences, then word windows.
- Size every piece with the embedding model's tokenizer, counting the heading line that is embedded with the
  chunk: at most **400 tokens** of bge-small-en-v1.5's 512, overlap up to **60 tokens** of whole units.
- A piece that would exceed the limit is split and counted (`cortex_ingest_truncation_splits_total`), never truncated.
- Chunk ids are deterministic (document, `chunking_version`, position, content hash), so unchanged chunks keep
  their ids across re-uploads and only changed chunks are re-embedded.

## Alternatives
Fixed 512-character windows (simple; truncation-prone, splits sentences); semantic chunking with an LLM (costly).
Staff step S.2 compares strategies on the held-out set with paired tests.

## Evidence
Corpus: 347 documents → 2,995 chunks; unit tests prove no chunk exceeds the budget and offsets map back to the text.
