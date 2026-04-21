# MyMory: Plugin and Skill Reference

> Install the plugin, extend the skills. The plugin is opinionated but every surface is editable.

## Plugin overview

The MyMory plugin ships as a Claude Cowork plugin. It also works as a Claude Code plugin; the skill definitions are shared. Installing either one wires the MyMory vault into your agent's default behavior.

The plugin is a wrapper around the MyMory CLI and MCP server. Every skill delegates to a Python entry point; you can call those same entry points from the shell without the plugin.

## Install

### Cowork

```
/plugin install mymory
```

Or, for the local-fork flow:

```
/plugin install-from-path "C:\Users\MAG MSI\Project Claude\Karpathy\mymory\plugin"
```

The plugin scaffold lives at `plugin/` in the repo. The plugin's `plugin.json` points Claude at the skill definitions and the MCP server launcher.

### Claude Code

```
claude plugin install ./plugin
```

Both installs put skill files under Claude's plugin cache and register the MCP server for on-session launch.

## Plugin manifest

```json
{
  "name": "mymory",
  "version": "0.1.0",
  "description": "Governed memory vault substrate with wings, corridors, and scheduled hygiene.",
  "mcp": {
    "command": "py",
    "args": ["-3", "-m", "mymory.mcp"]
  },
  "hooks": {
    "SessionEnd": "py -3 -m mymory.scripts.session_ingest"
  }
}
```

The `SessionEnd` hook runs the session ingest script at the end of every Cowork session. The MCP server starts on session begin and exposes `vault_*` tools.

## The eight skills

| Skill | Category | When it fires |
|-------|----------|---------------|
| `mymory-check-context` | Retrieval | Every substantive turn (default behavior) |
| `mymory-brief` | Summary | Morning or on "what's the status" |
| `mymory-curate` | Filing prep | Before a large ingest, or on "clean up X" |
| `mymory-recall` | Retrieval | User asks to find or remember |
| `mymory-remember` | Filing | User asks to save or log something |
| `mymory-convert` | Ingest | File path supplied, needs markdown |
| `mymory-ingest` | Ingest | Bulk import from a directory |
| `mymory-graphify` | Ingest | Repo path supplied |

Each skill has a `SKILL.md` under `plugin/skills/{name}/`. The SKILL.md describes triggers, default behavior, and the exact tool calls to make.

### mymory-check-context

Fires silently on every substantive turn. Calls `vault_query` with topic terms extracted from the current message, plus `vault_entities` on any entity names detected. Injects the top-K matches into context. Does not produce visible output unless invoked explicitly.

Default behavior note: "Asking the user a question the vault can answer is a protocol failure."

### mymory-brief

Generates or reads the latest morning brief. Variants:

- `brief` — print today's brief if it exists, else run hygiene's brief step
- `brief --full` — re-run all hygiene steps, not just brief
- `brief --since YYYY-MM-DD` — custom since-date

### mymory-curate

Pre-file review. Before an ingest, curate proposes:

- Wing/room placement for each staged note
- Entity extraction
- Supersession candidates (notes that look like drafts of existing canon)
- Duplicates (SHA collisions)

Curate never writes to the vault; it produces a review document at `_kks/{date}_curate_plan.md` and waits for confirmation.

### mymory-recall

Unified search. Semantic + grep + graph walk. Parameters:

- `query` — the search string
- `--k N` — top K results (default 10)
- `--wing W` — restrict to a wing
- `--grep` — grep-only (skip semantic)
- `--both` — union of semantic and grep
- `--walk N` — include N-hop graph neighborhood

Returns a ranked list of note paths with snippet excerpts and scoring breakdowns.

### mymory-remember

Filing a new note. Gathers:

- Title (prompted or extracted)
- Wing (proposed from entity detection, confirmed by user)
- Room (if the wing has rooms)
- Body (from conversation context or user supply)
- Referenced sources (from the vault pre-check)

Then calls `vault_file` which handles frontmatter, filename convention, backlink wiring.

### mymory-convert

Single-file conversion. File path in, markdown path out. Routes through `core/converter.py` with format detection. Does not file to vault; lands in a staging directory for curate or ingest to pick up.

### mymory-ingest

Bulk directory conversion + filing. Walks a directory, converts every supported format, stages outputs, runs curate, asks for confirmation, then files approved notes. This is the main onboarding flow.

Flags:

- `--dry-run` — show the plan, do nothing
- `--wing W` — force all new notes to a wing
- `--skip-curate` — file directly (use only for trusted sources)

### mymory-graphify

Repo ingest via vendored graphify. Produces one repo-level graph report, files it to `{wing}/room_repos/{repo_name}_graph_report.md`. Does NOT produce per-file notes.

Flags:

- `--wing W` — target wing (default: repo parent dir name)
- `--depth N` — graphify analysis depth
- `--only-summary` — skip full dependency graph, keep summary only

## Extending the plugin

Every skill body is editable. To customize a skill:

1. Locate the installed SKILL.md in your plugin cache (path printed by `claude plugin where mymory`).
2. Edit the triggers or body.
3. Restart your agent session.

Or, fork the skill into your own plugin:

1. Copy `plugin/skills/{skill_name}/` to your fork.
2. Change the triggers in frontmatter.
3. Register your fork alongside mymory (plugins compose).

## Writing a new skill

A skill is a folder under `plugin/skills/` containing:

```
plugin/skills/my-skill/
  SKILL.md
```

SKILL.md structure:

```markdown
---
name: my-skill
description: >
  One-paragraph triggering description with keywords the agent will match.
metadata:
  version: "0.1.0"
---

# Skill Title

Default behavior paragraph here.

## When to Run

Numbered list of trigger conditions.

## Procedure

Numbered list of exact steps, including tool calls.

## Exit Conditions

When to stop or fall back.
```

The description is the trigger keyword pool. The body is the agent's playbook.

## Extending the core

Beyond skills, the Python core is extensible at these points:

### Parsers

Add a new corpus parser in `mymory/parsers/`:

```python
# mymory/parsers/my_format.py
from mymory.parsers.base import Parser

class MyFormatParser(Parser):
    ext = ".myfmt"
    def parse(self, path):
        # return list of MarkdownNote objects
        ...
```

Register in `kks_manifest.yaml`:

```yaml
parsers:
  enabled:
    - pdf
    - docx
    - my_format
```

### Hooks

Graphify integration points are at `mymory/graphify/hooks.py`. Override `pre_ingest`, `post_ingest`, `pre_report`, `post_report` for custom behavior.

### Embedding model

Swap the sentence-transformers model in the manifest:

```yaml
embedding:
  model: "sentence-transformers/all-mpnet-base-v2"
  dim: 768
```

Next hygiene pass re-embeds everything (slow first run, incremental thereafter).

## MCP server tools

The MCP server exposes:

- `vault_query(query, k, wing?, entities?)` — semantic + grep search
- `vault_context(path, hops)` — note + N-hop neighborhood
- `vault_entities(name?)` — list or lookup entities
- `vault_wings()` — list wings with counts
- `vault_file(title, wing, body, entities, referenced, ...)` — create note

Connect from any MCP-capable client:

```json
{
  "mcpServers": {
    "mymory": {
      "command": "py",
      "args": ["-3", "-m", "mymory.mcp", "--vault", "C:\\path\\to\\vault"]
    }
  }
}
```

## Uninstall

```
/plugin uninstall mymory
```

This removes the plugin cache. The vault itself is untouched (vault-outside-repo rule).

---

Related: `docs/ARCHITECTURE.md` | `docs/TAXONOMY.md` | `docs/HYGIENE.md` | `README.md`
