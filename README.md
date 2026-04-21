# MyMory THIS WIP IS NOT READY FOR INSTALL YET!

> Open-source semantic knowledge vault.
> A MyMories + MemPalace + Graphify hybrid.
> Organize any set of files into a governed, searchable, agent-accessible knowledge graph.

MyMory is an installable plugin and Python package that turns a folder of conversations, documents, and code into a living Obsidian vault. The vault is plain markdown, agent-readable, searchable, and persistent across sessions. MyMory runs agentic when paired with an LLM host (Claude Code, Cowork, OpenClaw, Codex) and offline as a standalone CLI.

It is designed to work for any set of files. Your research library, your team's docs, your startup's scattered Drive exports, an academic corpus, a game canon. Not just one person's knowledge.

## Why MyMory

Modern LLM workflows leak knowledge. Every new session starts blind to what was decided yesterday. Retrieval-augmented pipelines drown in noise the moment the corpus exceeds a few hundred documents. Vaults bloat with per-file stubs that serve the graph visualisation and nothing else. Context fragments across projects with no way to navigate the overlaps.

MyMory addresses three failures:

1. **Session amnesia.** An agent that cannot read its own prior decisions repeats mistakes. MyMory gives every session a vault to consult before answering, and a filing step after answering.
2. **Corpus sprawl.** Raw files pile up faster than any human can curate them. MyMory handles the extraction, the conversion, the indexing, and the scheduled hygiene.
3. **Stub pollution.** The Obsidian graph turns into noise when every source code file gets its own node. MyMory enforces repo-level synthesis: code stays in the repo, the vault gets one synthesis note per project or subsystem.

## What is in the box

- **Python package** `mymory` with a single CLI entry point (`python -m mymory`)
- **Cowork / Claude Code plugin** with a set of amendable tool skills
- **MCP server** exposing `vault_query`, `vault_context`, `vault_entities`, `vault_file` to any MCP-speaking client
- **Document converter** for PDF, DOCX, PPTX, XLSX, HTML, CSV, TXT, RTF, MD (with OCR fallback for scanned PDFs)
- **Conversation parsers** for Cowork JSONL, Claude Code JSONL, ChatGPT export, Grok export, MyMories `.mmr`
- **Graphify fork** for code corpus analysis, vendored as `mymory.graphify`
- **Sentence-transformers index** (MiniLM-L6-v2, 384-dim, pickle or LanceDB)
- **py grep** full-text fallback for exact-term queries
- **Scheduled hygiene pipeline** that runs daily and files a morning brief
- **Templates** for wing notes, room notes, entity bridges, session logs, document conversions
- **Obsidian vault methodology** with wings, rooms, corridors, and canonical wikilink conventions

## Taxonomy: the default breakdown

MyMory organizes content along five axes. Every note lands at a coordinate in this space.

### 1. Temporal axis: Date

Every note is filed with a creation date (`YYYY-MM-DD`) in its filename and frontmatter. Scheduled hygiene sweeps produce a dated morning brief each day. Sessions are filed under the date they closed, not the date they started.

### 2. Topical axis: Subject matter

Each note has a topic slug in its filename (`{YYYY-MM-DD}_{topic_slug}.md`). Topics are detected heuristically from decision text, entity mentions, and file paths referenced in the source. Manual override is supported via `--slug`.

### 3. Corpus axis: Full conversation vs Document vs Code repo

MyMory treats three source types differently.

- **Conversations** (Cowork JSONL, ChatGPT, Grok, Claude Code): parsed, synthesised, filed under their primary wing as a session log. The raw transcript is archived compressed under `_conversations/` but the actionable synthesis lives at the wing.
- **Documents** (PDF, DOCX, PPTX, XLSX, HTML, CSV, TXT): converted to markdown verbatim, filed at their detected wing, original file path preserved in frontmatter (`source_file`). The binary stays where it is; the vault stays lightweight.
- **Code repos** (any directory): analysed by the vendored Graphify. The output is ONE repo-level synthesis note per code corpus plus a graph report. No per-file stubs.

### 4. Spatial axis: Wings and Rooms

Borrowed from the memory palace tradition via MemPalace.

- **Wings** are top-level domains. One wing per project, research area, or organizational unit. Wings map 1:1 to directories under the vault root. Examples: `strands/`, `research/`, `team-alpha/`, `personal/`.
- **Rooms** are second-level subdivisions within a wing. Used for wings that grow past a few hundred notes and need internal structure. Examples: `strands/game-canon/`, `research/papers/`, `team-alpha/meetings/`.
- **Corridors** are cross-wing links. When a topic appears in two wings, a corridor note lives under `_graph/` and wikilinks both sides. This is how MyMory prevents isolated silos.

Every note links to three anchors: its wing MOC (`_moc_{wing}.md`), the user identity (`_identity/USER.md`), and any detected entity bridges (`_graph/_entity_{slug}.md`).

### 5. Retrieval axis: Semantic + Keyword hybrid

Two retrieval paths run in parallel.

- **Semantic**: sentence-transformers MiniLM-L6-v2, 384 dimensions, cosine similarity, chunk granularity at markdown H2 section.
- **Keyword**: py grep (via `ripgrep`) for exact-term queries, entity name lookups, and anything where semantic retrieval returns false positives.

The `mymory-recall` skill runs both and merges the result set with deduplication.

## Architecture in one diagram

```
     ┌───────────────────────────────────────────────────────┐
     │                     INGEST LAYER                      │
     │  Cowork JSONL   ChatGPT   Grok   .mmr   Claude Code   │
     │           PDF   DOCX   PPTX   XLSX   HTML   CSV       │
     │                  Code repo (any dir)                  │
     └──────────┬────────────────────┬───────────────┬───────┘
                │                    │               │
                ▼                    ▼               ▼
        ┌──────────────┐    ┌──────────────┐  ┌────────────┐
        │   parsers/   │    │  converter/  │  │ graphify/  │
        │ conversation │    │  document    │  │ code repo  │
        │   → Turn[]   │    │  → markdown  │  │ → synthesis│
        └──────┬───────┘    └──────┬───────┘  └──────┬─────┘
               │                   │                 │
               └───────────┬───────┴─────────────────┘
                           ▼
                 ┌──────────────────┐
                 │  taxonomy/       │
                 │  wing detection  │
                 │  room binning    │
                 │  entity bridges  │
                 └─────────┬────────┘
                           ▼
     ┌────────────────────────────────────────────────┐
     │               OBSIDIAN VAULT                   │
     │   {wing}/{YYYY-MM-DD}_{topic_slug}.md          │
     │   + frontmatter + wikilinks + Related Notes    │
     └──────┬──────────────────────┬──────────────────┘
            │                      │
            ▼                      ▼
     ┌────────────┐         ┌─────────────┐
     │ embedder   │         │   curator   │
     │ MiniLM     │         │ daily pass  │
     │ 384d       │         │ 05:30 SGT   │
     └─────┬──────┘         └──────┬──────┘
           │                       │
           ▼                       ▼
     ┌────────────────────────────────────┐
     │            RETRIEVAL API           │
     │     semantic + py grep hybrid      │
     │     vault_query / vault_context    │
     │     vault_entities / vault_file    │
     └────────────────┬───────────────────┘
                      │
                      ▼
     ┌────────────────────────────────────┐
     │       PLUGIN SKILLS LAYER          │
     │  brief  curate  recall  remember   │
     │  convert  ingest  graphify  check  │
     └────────────────────────────────────┘
```

## Design principles

1. **Vault outside repo.** MyMory the code lives in one place. The vault it builds lives in another. Never conflate them. A user running `pip install mymory` should not have to think about where the repo ended up.
2. **No per-file code stubs.** Code files stay in the code repo. The vault gets repo-level or subsystem-level synthesis. Graphify outputs go to one wing-level note plus a graph report, never fragmented per source file.
3. **Agentic and offline.** The CLI runs standalone. The plugin adds agent integration. Every feature works without an LLM call; LLM-based distillation is optional and batched.
4. **Reversible.** Everything is plain markdown with wikilinks. If you uninstall MyMory, the vault keeps working in Obsidian.
5. **Generic.** MyMory does not assume one specific user. Wings and rooms are user-defined. Entity dictionaries are extensible via YAML manifest.
6. **Append-only by default.** Notes are never destructively overwritten. Supersession is tracked via `supersedes:` frontmatter. Deletion requires explicit user confirmation.

## Quick start

### Install

MyMory is pre-release (v0.1.0, alpha). There is no PyPI artifact yet; install from source.

**Prerequisites**

- Python 3.10 or newer (tested on 3.10 - 3.13)
- Roughly 500 MB disk for the sentence-transformers model (downloaded on first `mymory recall` / `mymory curate`)
- Optional: `ripgrep` on `$PATH` for fast keyword retrieval (falls back to pure-Python `grep` if absent)
- Optional: a C compiler for `pymupdf` wheels on exotic platforms; standard wheels cover Windows, macOS, and Linux x86_64/arm64

**Editable install from a local clone (recommended while MyMory is pre-release)**

```bash
git clone https://github.com/uddin/mymory.git
cd mymory
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# macOS / Linux:       source .venv/bin/activate
pip install -e .
```

This exposes the `mymory` console script (defined at `[project.scripts]` in `pyproject.toml`) and lets you edit the package in place.

**Ephemeral run without install (useful for contributors)**

```bash
git clone https://github.com/uddin/mymory.git
cd mymory
pip install -r <(python -c "import tomllib,sys; [print(d) for d in tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']]")
python -m mymory --help
```

Or set `PYTHONPATH` to the repo root and invoke the module directly: useful if you want to point at a working copy without `pip install -e .`:

```bash
# Windows PowerShell
$env:PYTHONPATH = "C:\path\to\mymory"
python -m mymory --help

# macOS / Linux
PYTHONPATH=/path/to/mymory python -m mymory --help
```

**Optional extras**

```bash
pip install -e ".[mcp]"        # MCP server (vault_query, vault_context, ...)
pip install -e ".[lancedb]"    # LanceDB index backend (replaces pickle default)
pip install -e ".[dev]"        # pytest, black, ruff, mypy
pip install -e ".[all]"        # everything above
```

**Future: PyPI release**

```bash
pip install mymory             # NOT YET AVAILABLE — tracked for v0.5 per Roadmap
```

### Initialize a vault

```bash
mymory init ~/my-vault
# creates the vault scaffold with _identity, _graph, _templates, _kks, HOME.md
```

### Ingest a conversation log

```bash
mymory ingest ~/.claude/projects/my-project/session-abc123.jsonl
# parses, extracts decisions and entities, files to the detected wing
```

### Convert a document

```bash
mymory convert ~/Downloads/architecture-spec.pdf --wing research
# PDF → markdown, filed under research/{date}_architecture-spec.md
```

### Graph a code repo

```bash
mymory graphify ~/Projects/my-service --wing engineering
# runs graphify, produces ONE synthesis note + GRAPH_REPORT.md
```

### Recall

```bash
mymory recall "what did we decide about the payment rail"
# semantic + grep hybrid, returns top matches with context
```

### Install the plugin

```bash
mymory plugin install cowork
# registers the plugin with your Cowork install
# adds skills, registers the MCP server, installs the scheduled hygiene task
```

## Plugin skills

The Cowork plugin ships with eight default skills. Each maps to a CLI subcommand and is editable by the end user at `{plugin_root}/skills/<skill-name>/SKILL.md`.

| Skill | Purpose | CLI equivalent |
|---|---|---|
| `mymory-check-context` | Vault-first context retrieval before answering | `mymory context <topic>` |
| `mymory-brief` | Morning brief: filings, drift, supersession proposals | `mymory brief` |
| `mymory-curate` | Full curation pass: dedup, entity bridges, staleness | `mymory curate` |
| `mymory-recall` | Semantic + grep hybrid search | `mymory recall <query>` |
| `mymory-remember` | File the current session into the vault | `mymory ingest --current-session` |
| `mymory-convert` | Convert a document to vault markdown | `mymory convert <path>` |
| `mymory-ingest` | Parse and import a conversation log | `mymory ingest <path>` |
| `mymory-graphify` | Generate a code corpus graph at wing level | `mymory graphify <dir>` |

Skills are amendable. Users can edit descriptions, procedures, trigger phrases, and default behaviour per installation.

## Daily hygiene

MyMory ships with a scheduled task that runs at 05:30 local time by default. The task performs:

1. **Filing audit.** Scan every project CONTEXT.md for unfiled session candidates. File any that pass validation.
2. **Vector refresh.** Incremental embed of notes created or modified since the last run.
3. **Curation pass.** Entity bridge gap detection, supersession proposals, staleness drift (banned-token sweep).
4. **Semantic probes.** Validate embedding health with canonical queries. Flag if recall quality has drifted.
5. **Morning brief.** Emit `_kks/{YYYY-MM-DD}_morning_brief.md` summarising the day's activity and any gaps.

The schedule, the banned-token list, and the probe set are all user-editable via `_kks/kks_manifest.yaml`.

## Repository layout

```
mymory/                         # the product repo (this)
├── README.md                   # this file
├── LICENSE
├── pyproject.toml              # Python package config
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md         # full architecture spec
│   ├── TAXONOMY.md             # wings / rooms / corridors detail
│   ├── HYGIENE.md              # daily hygiene pipeline spec
│   └── PLUGIN.md               # plugin install + skill reference
├── mymory/                     # Python package
│   ├── __init__.py
│   ├── __main__.py             # python -m mymory entry point
│   ├── cli.py                  # subcommand dispatch
│   ├── config.py               # manifest loader
│   ├── core/
│   │   ├── converter.py        # doc → markdown
│   │   ├── embedder.py         # sentence-transformers wrapper
│   │   ├── searcher.py         # semantic + grep hybrid
│   │   ├── curator.py          # hygiene pass
│   │   ├── filer.py            # vault write + backlinks
│   │   └── brief.py            # morning brief composer
│   ├── parsers/
│   │   ├── cowork_jsonl.py
│   │   ├── claude_code.py
│   │   ├── chatgpt.py
│   │   ├── grok.py
│   │   └── mymories.py         # .mmr format
│   ├── graphify/               # vendored from safishamsi/graphify
│   ├── taxonomy/
│   │   ├── wings.py            # wing detection heuristics
│   │   ├── rooms.py            # room partitioning
│   │   └── entities.py         # entity extraction + bridging
│   ├── compression/
│   │   └── mmr.py              # MyMories .mmr read/write
│   └── mempalace/
│       └── palace.py           # wings/rooms spatial primitives
├── plugin/                     # Cowork plugin source
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── .mcp.json
│   ├── mcp-server/
│   │   ├── package.json
│   │   └── server.mjs          # vault_query / vault_context / vault_entities / vault_file
│   ├── hooks/
│   │   └── hooks.json          # SessionEnd auto-file trigger
│   └── skills/
│       ├── mymory-check-context/SKILL.md
│       ├── mymory-brief/SKILL.md
│       ├── mymory-curate/SKILL.md
│       ├── mymory-recall/SKILL.md
│       ├── mymory-remember/SKILL.md
│       ├── mymory-convert/SKILL.md
│       ├── mymory-ingest/SKILL.md
│       └── mymory-graphify/SKILL.md
├── scheduled/
│   └── daily_hygiene.json      # scheduled task manifest
├── templates/                  # Obsidian-ready vault templates
│   ├── wing-note.md
│   ├── room-note.md
│   ├── entity-bridge.md
│   ├── session-log.md
│   └── document-conversion.md
├── config/
│   ├── default_manifest.yaml   # starter kks_manifest
│   └── entities.yaml           # default entity patterns
└── tests/
    ├── test_converter.py
    ├── test_parsers.py
    ├── test_curator.py
    ├── test_searcher.py
    └── fixtures/
```

## How MyMory differs from plain RAG

Retrieval-augmented generation grows unbounded and noisy. MyMory is governed and bounded.

- **Semantic alignment, not similarity pile.** Entities cluster by usage context, not just cosine distance. Corridors are explicit cross-wing pointers, not implicit nearest-neighbour traversals.
- **Curation is a first-class step.** Daily hygiene runs supersession, dedup, and drift detection. A fact marked superseded does not return in recall unless explicitly requested.
- **Source provenance is preserved.** Every note carries `source_file`, `source_agent`, and `source_model` frontmatter. You can always trace back to where something came from.
- **No per-file stubs.** Code does not get one vault note per file. It gets one synthesis per repo or subsystem via Graphify. The graph stays navigable.
- **Markdown, not a proprietary blob.** The vault is readable in Obsidian, grep-able with any tool, portable to any other system. MyMory the product can go away and the vault keeps working.

## Positioning

MyMory is the hybrid that bridges three projects that should have been one.

- **MyMories** pioneered reversible session compression and the `.mmr` portable format. MyMory keeps `.mmr` compatibility and extends the compression to vault-level archival.
- **MemPalace** mapped the wings / rooms spatial metaphor onto knowledge graphs. MyMory adopts the taxonomy and adds corridors as an explicit cross-wing primitive.
- **Graphify** solved code corpus understanding with `/graphify .` in any AI coding assistant. MyMory vendors graphify as its code analysis layer and constrains output to repo-level synthesis to prevent vault pollution.

Together, the three become a single product for organizing any set of files into a governed, agent-accessible knowledge graph.

## Roadmap

- **v0.1** (current): Scaffold, spec, README, plugin manifest, taxonomy docs. Code-complete: document converter.
- **v0.2**: Parsers (Cowork JSONL, Claude Code JSONL). Embedder. Filer with backlinks.
- **v0.3**: Graphify vendored. Plugin skills live. Scheduled hygiene runnable.
- **v0.4**: Full historical import tested. Vault hygiene pass validated. Recall benchmarks published.
- **v0.5**: ChatGPT, Grok, MyMories `.mmr` parsers. MCP server shipped.
- **v1.0**: Open-source release. Public plugin marketplace listing.

Each release tag publishes a CHANGELOG entry, a migration note for vault format changes (if any), and a reproducible test run.

## Contributing

MyMory is designed to be amended. The plugin skills, the entity patterns, the hygiene schedule, and the banned-token list are all user-editable without touching the Python code.

- Skills: edit `plugin/skills/<name>/SKILL.md`
- Entity patterns: edit `config/entities.yaml`
- Hygiene schedule: edit `scheduled/daily_hygiene.json`
- Manifest defaults: edit `config/default_manifest.yaml`

Pull requests welcome on parsers, converters, and graphify adapters for additional AI coding assistants.

## Credits

- **Graphify** by Safi Shamsi. Vendored under original license. <https://github.com/safishamsi/graphify>
- **MemPalace** wings / rooms taxonomy. Adapted with attribution.
- **MyMories** `.mmr` format. Compatibility maintained.
- **sentence-transformers** by UKPLab.
- **Obsidian** as the canonical vault reader.

## License

MIT. See `LICENSE`.
