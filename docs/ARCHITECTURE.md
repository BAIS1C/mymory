# MyMory: Architecture

> The full technical spec. The README is the marketing. This is the map.

## 1. Design goals

MyMory is a governed memory substrate for AI sessions, personal corpora, and team knowledge. It has four non-negotiable properties:

1. **Agentic and offline.** Every retrieval, curation, and filing step runs locally with no external API. A Claude Cowork plugin layers agentic orchestration on top, but the substrate works without it.
2. **Vault-outside-repo.** The Obsidian vault is the human surface. The code repo is the machine surface. They live in separate filesystems so the graph stays clean and the repo stays small.
3. **Append-only by default.** No destructive edits to vault content without explicit user confirmation. Supersession via new dated notes, never overwrite.
4. **Generic substrate.** Wings, rooms, corridors, and taxonomies are declared per-vault via `kks_manifest.yaml`. Nothing in the core assumes Sean Uddin, Strands, or any specific ontology.

## 2. System layers

```
Layer 5: Plugin skills (Cowork + Claude Code)
          check-context | brief | curate | recall | remember
          convert | ingest | graphify
                          |
Layer 4: Orchestration (Python CLI + MCP server)
          mymory.cli | mymory.mcp
                          |
Layer 3: Retrieval (semantic + grep + graph)
          embed.py | search.py | grep_fallback.py
                          |
Layer 2: Graph construction
          graphify/ (vendored) | corridors.py | backlinks.py
                          |
Layer 1: Taxonomy + wings
          taxonomy.py | wings.py | rooms.py
                          |
Layer 0: Ingest + conversion
          converter.py | parsers/ | dedup.py
                          |
                  [Source corpora]
  PDF | DOCX | PPTX | XLSX | HTML | CSV | TXT | RTF | MD
  Cowork JSONL | ChatGPT export | Grok export
  Claude Code JSONL | MyMories .mmr snapshots
```

Each layer consumes only the layers below. A failed upper layer never corrupts a lower one.

## 3. Layer 0: Ingest and conversion

`core/converter.py` handles format conversion. Every source file runs through a SHA256 dedup check (files with matching content hashes produce a single canonical note).

Supported conversions:

| Format | Library | Output |
|--------|---------|--------|
| PDF | PyMuPDF (fitz) | Markdown with page breaks preserved |
| DOCX | python-docx | Markdown with heading hierarchy |
| PPTX | python-pptx | Markdown with one section per slide |
| XLSX | openpyxl | Markdown table per sheet |
| HTML | beautifulsoup4 + markdownify | Markdown |
| CSV | pandas | Markdown table |
| TXT / RTF / MD | native / striprtf | passthrough or direct copy |
| Cowork JSONL | `parsers/cowork.py` | One markdown note per session |
| ChatGPT export | `parsers/chatgpt.py` | One note per conversation |
| Grok export | `parsers/grok.py` | One note per conversation |
| Claude Code JSONL | `parsers/claude_code.py` | One note per session |
| MyMories .mmr | `parsers/mmr.py` | Direct import with governance preserved |

Output goes to a staging directory, not straight to the vault. Staging lets the curate step reject garbage before it pollutes the graph.

## 4. Layer 1: Taxonomy, wings, rooms

Every note lands at a canonical path derived from five axes:

- **Date**: YYYY-MM-DD from frontmatter or file mtime
- **Subject**: topic slug, extracted or manually tagged
- **Corpus**: which source corpus it came from (sessions / papers / chats / docs / etc.)
- **Spatial**: `{wing}/{room}/{note}` path in the Obsidian vault
- **Retrieval**: embedding vector + grep tokens (deferred to Layer 3)

### Wings

A **wing** is a top-level Obsidian folder representing a major domain. Examples from Sean's MKV:

```
claude/      -- AI work, models, sessions
strands/     -- Strands ecosystem, tokenomics
mymory/      -- This project's own notes
fintrek/     -- Fintrek Trader
uddin/       -- Personal
```

Wings are declared in `kks_manifest.yaml`. Renaming a wing requires a migration run, not a config edit alone.

### Rooms

A **room** is a subfolder inside a wing. Rooms break a large wing into navigable spaces. Examples:

```
strands/
  room_canon/        -- Canonical architecture notes
  room_tokenomics/   -- Economic design
  room_asset_pipeline/ -- ComfyUI, LTX, generation
```

Rooms are optional. A wing without rooms is a flat folder. Rooms are useful when a wing crosses 50+ notes.

### Corridors

A **corridor** is a cross-wing entity bridge. Corridors live in `_graph/_entity_{slug}.md` and list every note referencing the entity, grouped by wing. Corridors keep the Obsidian graph dense even when notes sit in different wings.

Corridors are built by `layer2/corridors.py`, which scans all notes for entity mentions and materializes the bridge file. Corridors regenerate on every hygiene run.

## 5. Layer 2: Graph construction

### Graphify integration

MyMory vendors Safi Shamsi's [graphify](https://github.com/safishamsi/graphify) into `mymory/graphify/`. Graphify is repo-level, not file-level: it produces a single markdown graph report per project, not a note per source file. This matches the design principle **no per-file code stubs in the vault**.

When a repo is ingested:

1. Graphify runs on the repo root.
2. It produces `{repo_name}_graph_report.md` with the dependency graph, module map, and architectural summary.
3. The report lands in `{wing}/room_repos/{repo_name}_graph_report.md` (not `note_per_file/...`).
4. Corridors link the repo report to any entity it references.

Individual source files are never imported as separate notes. If a function or class needs its own note, a human creates it explicitly.

### Backlinks

`layer2/backlinks.py` runs after every ingest. It scans each new note's `referenced:` frontmatter field and appends a `## Referenced By` line to each source note. The operation is idempotent: re-running produces no duplicates.

### Entity detection

`layer2/entities.py` holds a canonical entity list per-vault (configured in `kks_manifest.yaml`). On ingest, entity names are matched against note bodies; each hit adds a wikilink to the note's Related Notes footer and triggers a corridor update.

## 6. Layer 3: Retrieval

Two retrieval modes, union of results:

### Semantic

`layer3/embed.py` uses `sentence-transformers/all-MiniLM-L6-v2` (384 dim, ~90MB). Embeddings persist to `.embed_cache/embeddings.pkl` (dict: note path → vector) or a LanceDB store when `lancedb` is installed.

Query flow:

1. Embed the query string.
2. Cosine similarity against all stored vectors.
3. Return top-K matches above threshold (default 0.35).

Re-embed pass runs on hygiene schedule, picking up any note whose mtime exceeds its last-embed timestamp.

### Grep fallback

`layer3/grep_fallback.py` wraps ripgrep (bundled or system). Useful when semantic misses exact tokens (code symbols, error strings, commit hashes).

```python
mymory recall "ERR_BADSIG_517" --grep
```

### Graph walk

`layer3/graph_walk.py` traverses wikilinks and corridors. Given a starting note, returns the N-hop neighborhood. Used by the `brief` skill to assemble morning context.

## 7. Layer 4: Orchestration

### CLI

```
mymory init [--vault PATH]         Scaffold a new vault
mymory ingest PATH [--wing WING]   Import files/dir into vault
mymory convert PATH [OUT]          Convert a single file to markdown
mymory recall QUERY [--grep --k N] Search the vault
mymory graphify REPO [--wing WING] Run graphify on a repo
mymory hygiene                     Run the daily pipeline
mymory brief                       Print morning brief
mymory stats                       Show vault statistics
```

Entry point: `mymory/cli.py` using `click`.

### MCP server

`mymory/mcp.py` exposes vault tools to MCP clients (Cowork, Claude Code, any MCP-capable agent). Tools:

- `vault_query`: keyword + semantic search
- `vault_context`: fetch a note plus N-hop neighborhood
- `vault_entities`: list entities and their corridor counts
- `vault_wings`: list wings and note counts
- `vault_file`: create a new note with backlinks

Transport: stdio by default, TCP optional for remote use.

## 8. Layer 5: Plugin skills

Eight skills ship with the Cowork plugin:

| Skill | Trigger | Action |
|-------|---------|--------|
| check-context | Every substantive turn | Silent vault query, inject relevant context |
| brief | Morning or on request | Assemble daily brief from hygiene outputs |
| curate | Pre-file review | Propose entity extractions, room placement |
| recall | User asks to find | Semantic + grep search with ranked results |
| remember | User asks to save | Draft a new note with frontmatter + backlinks |
| convert | File path given | Route through converter.py with format detection |
| ingest | Bulk import | Run full ingest pipeline on a directory |
| graphify | Repo path given | Run graphify and file the graph report |

Each skill has its own `SKILL.md` in `plugin/skills/{name}/SKILL.md` declaring triggers, parameters, and exit conditions.

## 9. Hygiene pipeline

Daily scheduled task (default 05:30 local). Five steps, each skippable via manifest:

1. **Re-embed drift.** Any note with mtime > last-embed-timestamp gets re-embedded.
2. **Rebuild corridors.** Entity bridges regenerate from scratch. Stale corridors drop.
3. **Supersession scan.** Notes marked `superseded_by: <path>` in frontmatter get their `## Referenced By` pointers redirected.
4. **Dedup pass.** SHA256 hash collisions logged to hygiene report; human reviews before deletion.
5. **Morning brief.** Fresh notes since last run, top open items per wing, entity gaps.

Report lands at `_kks/{YYYY-MM-DD}_kasai_morning_brief_{HHMM}.md`.

Full detail in `docs/HYGIENE.md`.

## 10. Data at rest

```
vault/
  {wing}/
    {room}/?
      {YYYY-MM-DD}_{slug}.md   -- individual notes
    _moc_{wing}.md              -- wing map-of-content
  _graph/
    _entity_{slug}.md           -- corridors
  _kks/
    {YYYY-MM-DD}_*_brief_*.md   -- morning briefs
  _identity/
    USER.md                     -- vault operator identity
    MEMORY.md                   -- environment facts
  HOME.md                       -- vault entry point
  CONTEXT.md                    -- link-stub session log
  CLAUDE.md                     -- AI operator protocol
  .embed_cache/
    embeddings.pkl              -- vector store
    embed_log.jsonl             -- re-embed history
```

Repo layout is separate; see `docs/PLUGIN.md`.

## 11. Security and privacy

- No network calls from Layer 0-3. All processing local.
- Layer 4 MCP server binds to localhost by default.
- Layer 5 plugin skills run under the user's Cowork/Claude Code session; no external agent sees vault contents without an active session.
- `uddin` (personal) wing uses stub-only policy: notes contain metadata and pointers, never full personal content.
- `.embed_cache/` is gitignored by default. Vaults are not intended for git versioning; back up manually or via file-level snapshot tools.

## 12. Extension points

Every surface below is designed to be overridden by the vault operator:

- `kks_manifest.yaml`: wings, rooms, entities, hygiene schedule, retrieval thresholds
- `plugin/skills/*/SKILL.md`: skill triggers and bodies
- `mymory/parsers/`: add a new parser for a new corpus format
- `mymory/graphify/hooks.py`: graphify extension hooks
- `docs/TAXONOMY.md`: document your own ontology decisions

## 13. What MyMory is not

- Not a RAG pipeline. RAG retrieves chunks; MyMory retrieves governed notes with provenance.
- Not a note-taking app. Obsidian is that. MyMory is the layer underneath.
- Not a chat history archiver. It is that plus corpus ingestion plus graph construction plus scheduled hygiene.
- Not a LanceDB/Chroma wrapper. The vector store is swappable; the substrate is the point.

## 14. Versioning

MyMory follows semver on the package and calendar versioning on the vault schema. Schema changes ship with migration scripts in `migrations/`.

Current schema: `v0.1` (frontmatter fields: title, project, wing, created, source_agent, source_model, confidence, tags, entities, referenced, superseded_by).

---

Related docs: `docs/TAXONOMY.md` | `docs/HYGIENE.md` | `docs/PLUGIN.md` | `README.md`
