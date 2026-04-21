# MyMory: Taxonomy

> How knowledge is filed. Five axes, one canonical path.

## Why five axes

Most personal knowledge systems file by one axis, usually date or topic. That works until the corpus grows past a few hundred notes. Past that, you need cross-indexing, otherwise retrieval collapses to full-text grep and the graph becomes noise.

MyMory files along five simultaneous axes. Every note sits at a canonical location but is discoverable through five independent lookups.

| Axis | What it answers | Storage |
|------|----------------|---------|
| Date | When was this captured? | Filename prefix `YYYY-MM-DD` |
| Subject | What is it about? | Slug in filename + tags + entities |
| Corpus | Where did it come from? | `source_agent` + `source_model` frontmatter |
| Spatial | Where does it live in my mental map? | `{wing}/{room}/` folder path |
| Retrieval | How do I find it later? | Embedding vector + grep tokens |

## Axis 1: Date

Every filename starts with `YYYY-MM-DD`. This is non-negotiable. No filename without a date prefix.

```
2026-04-21_vault_first_protocol_ship.md
```

The date is the **creation date**, not the modified date. Supersession creates a new note with a new date; it does not overwrite. This preserves chronology.

### Why date first

Date-first filenames give you three properties for free:

1. Lexicographic sort equals chronological sort in any file browser.
2. Duplicate-subject notes stay distinguishable (two notes about the same topic on different days).
3. Trivial "notes from last week" queries work without touching the graph.

### Supersession

When a note becomes canonical-obsolete, do not delete it. Create a new dated note and add `superseded_by: {path}` to the old note's frontmatter. The hygiene pass redirects `## Referenced By` pointers to the new note on its next run.

## Axis 2: Subject

The slug portion of the filename is the subject handle:

```
2026-04-21_vault_first_protocol_ship.md
           \_____ subject slug _____/
```

Slug rules:

- lowercase, underscore-separated
- verb-noun or noun-noun phrases, max 6 words
- no project name in the slug (the wing already encodes project)
- no dates in the slug (the date prefix already does that)

Three slots carry additional subject information:

- `title:` frontmatter field — human-readable title, full punctuation
- `tags:` frontmatter — topical tags, lowercase, hyphenated
- `entities:` frontmatter — canonical entity names from the vault's entity list

## Axis 3: Corpus

Every note declares where it came from:

```yaml
source_agent: "claude-cowork"     # or "chatgpt-web", "grok-mobile", "human", ...
source_model: "claude-opus-4"     # or "gpt-4o", "grok-3", null for human notes
confidence: DERIVED                # VERBATIM | DERIVED | SPECULATIVE | CANONICAL
```

Corpus provenance matters because retrieval should be source-aware. A synthesis from a Claude Cowork session and a screenshot of a GPT-4 chat are not equally authoritative for the same question.

Corpus declarations also drive the `_moc_corpus.md` aggregator views that Obsidian dataview queries can consume.

### Confidence levels

| Level | Meaning |
|-------|---------|
| VERBATIM | Direct conversion of source content (ingested PDF text, chat export) |
| DERIVED | Synthesized by an AI from conversation or source |
| SPECULATIVE | Proposal or hypothesis, not yet confirmed |
| CANONICAL | Human-authored, authoritative, not auto-editable |

`CANONICAL` is protected: scripts never modify canonical notes without an explicit `--force` flag and a staged diff.

## Axis 4: Spatial (wings, rooms, corridors)

This is the axis borrowed from memory palace tradition and MemPalace specifically. Notes live at `{wing}/{room}?/{note}.md`.

### Wings

A wing is a top-level domain. Think of it as a separate building in your knowledge campus. Examples:

```
claude/       -- AI work, sessions, research
strands/      -- One specific major project
mymory/       -- This project's own self-reference notes
fintrek/      -- Another major project
uddin/        -- Personal stub wing
```

Wings are declared in `kks_manifest.yaml`:

```yaml
wings:
  claude:
    label: "Claude Wing"
    description: "AI work, model research, session logs"
  strands:
    label: "Strands Wing"
    description: "Strands ecosystem"
```

### Rooms

A room is a subfolder inside a wing. Rooms are optional; a flat wing is fine for the first ~50 notes. Past that, rooms help navigation.

```
strands/
  room_canon/
  room_tokenomics/
  room_asset_pipeline/
  room_sessions/
```

Room naming: always prefix with `room_` for unambiguous sorting against non-room items at the wing root (MOCs, README, entity aliases).

Rooms are also declared per-wing in the manifest:

```yaml
wings:
  strands:
    rooms:
      - canon
      - tokenomics
      - asset_pipeline
      - sessions
```

### Corridors

A corridor is a cross-wing bridge. Corridors are NOT folders. They are special notes in `_graph/_entity_{slug}.md` that aggregate every reference to an entity across all wings.

Example structure of a corridor file:

```markdown
---
title: "Graphify"
type: entity
created: 2026-04-16
---

# Graphify

> Referenced in 16 notes across 2 wings.
> [[USER|Sean Uddin]] | [[HOME|Vault Home]]

## [[_moc_claude|Claude Wing]] (15)

- [[2026-04-14_graphify_architecture|Architecture]]
- [[2026-04-14_httpx_review|Graphify Evaluation — httpx]]
- ...

## [[_moc_strands|Strands Wing]] (1)

- [[2026-04-14_kasai_knowledge_stack_architecture_v1|...]]
```

Corridors regenerate on every hygiene pass. Never edit a corridor by hand; edit the source notes and let the pass rebuild.

### What is NOT a wing

- A single project's subfolder — that's a room inside its parent wing
- A tag — tags cross wings; wings are spatial
- An entity — entities are corridors, not wings
- A year — dates are axis 1, not axis 4

## Axis 5: Retrieval

Retrieval-by-embedding and retrieval-by-grep are kept separate so each optimizes for its strength.

### Semantic

Each note is embedded once on ingest and re-embedded on mtime drift. The embedding function is declared in `kks_manifest.yaml`:

```yaml
embedding:
  model: "sentence-transformers/all-MiniLM-L6-v2"
  dim: 384
  store: "pickle"     # or "lancedb"
  threshold: 0.35
  top_k: 10
```

Retrieval merges frontmatter metadata with embedding similarity:

```python
# pseudocode
results = cosine_topk(query_vec, all_vecs, k=20)
filtered = [r for r in results if r.score >= threshold]
filtered = boost_by_wing(filtered, user_current_wing)
filtered = boost_by_entity_overlap(filtered, query_entities)
return filtered[:top_k]
```

### Grep

`layer3/grep_fallback.py` runs when semantic misses would hurt (short queries, exact-token matches):

```
mymory recall "ERR_BADSIG_517"          # auto-grep if query looks token-like
mymory recall "authentication" --grep    # force grep
mymory recall "authentication" --both    # union of semantic + grep
```

### Graph walk

Given a starting note, walk wikilinks and corridors N hops outward. The `brief` and `curate` skills use this for context assembly.

## File and path conventions

| Pattern | Meaning |
|---------|---------|
| `{wing}/{YYYY-MM-DD}_{slug}.md` | Standard note |
| `{wing}/room_{room}/{YYYY-MM-DD}_{slug}.md` | Note in a room |
| `{wing}/_moc_{wing}.md` | Wing map of content |
| `_graph/_entity_{slug}.md` | Entity corridor |
| `_kks/{YYYY-MM-DD}_kasai_morning_brief_{HHMM}.md` | Hygiene output |
| `_identity/USER.md` | Vault operator identity |
| `_identity/MEMORY.md` | Environment facts |
| `HOME.md` | Vault entry point |
| `CONTEXT.md` | Link-stub session log (append-only) |

## Project, repo, folder alignment

This is the rule Sean called out explicitly. Everything in the vault is **project/repo/folder arranged**.

What that means in practice:

- A project gets a wing.
- A repo inside a project gets a room (or if the project has one repo, it gets the wing itself).
- A folder inside a repo does NOT get its own note. The repo as a whole gets one graphify-generated report.
- Cross-project entities get corridors. That's the linking mechanism.

What you never see in a clean MyMory vault:

- One note per source file (that's stub pollution)
- Individual function or class definitions as notes
- Raw code blocks checked into the vault
- Implementation details of vendored dependencies

If the question is "how does X work in code," the answer lives in the repo. If the question is "what did we decide about X," the answer lives in the vault.

## Cross-corpus semantic alignment

When two notes from different corpora discuss the same entity, they should surface together in retrieval. The hygiene pass enforces this by:

1. Rebuilding corridors (Axis 4 cross-wing links)
2. Recomputing entity neighborhoods (which corridors share the most notes)
3. Logging suspected aliases to the morning brief (entity A and entity B always co-occur; propose alias)

Aliases, once confirmed by a human, land in `kks_manifest.yaml` under `entity_aliases:` and collapse on the next pass.

## Migration from flat notes

If you are starting from a pile of dated flat notes (no wings), run:

```
mymory migrate flat-to-wings --dry-run
```

It proposes wing assignments based on tag + entity co-occurrence clustering. Nothing moves until you confirm the plan.

---

Related: `docs/ARCHITECTURE.md` | `docs/HYGIENE.md` | `README.md`
