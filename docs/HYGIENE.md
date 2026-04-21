# MyMory: Hygiene

> The pipeline that keeps the vault honest. Runs daily. Never destructive without confirmation.

## Why hygiene matters

Vaults rot. Notes accumulate, embeddings go stale, corridors drift, entity mentions get out of sync, duplicate content piles up. Without a scheduled pass, a vault degrades into a lossy grep index. The hygiene pipeline is MyMory's answer.

Hygiene is a read-mostly process. It **never deletes** without an explicit flag. Everything it does is reversible by restoring the previous day's backup (if one exists) or by re-running with the inverse operation.

## When it runs

Default: daily, 05:30 local time. Configurable per vault:

```yaml
# kks_manifest.yaml
hygiene:
  schedule: "05:30"
  enabled: true
  notify_on_completion: false
```

Triggered manually:

```
mymory hygiene                    # full pass
mymory hygiene --dry-run          # report what would change, no writes
mymory hygiene --only embed       # single step
```

## The five steps

### Step 1: Re-embed drift

Any note whose `mtime` exceeds its last-embed timestamp gets re-embedded. Implementation:

```python
for note in vault.all_notes():
    if note.mtime > embed_cache.last_embed(note.path):
        vec = embed(note.body_without_frontmatter)
        embed_cache.set(note.path, vec, embedded_at=now())
```

The model is `sentence-transformers/all-MiniLM-L6-v2` by default (384 dim, ~90MB, CPU-fast). Configurable to any sentence-transformers model.

Store backends:

- **Pickle dict** (default): `.embed_cache/embeddings.pkl`, a single dict mapping note path to vector. Simple, no dependencies beyond sentence-transformers. Works up to ~100K notes before load time becomes annoying.
- **LanceDB** (optional): enable with `store: "lancedb"` in manifest. Scales to millions of notes, supports approximate nearest neighbor queries.

Drift log: `.embed_cache/embed_log.jsonl` records every re-embed with timestamp, model, vector dim. This is the audit trail.

### Step 2: Rebuild corridors

`_graph/_entity_{slug}.md` files regenerate from scratch. The pass:

1. Loads the canonical entity list from `kks_manifest.yaml`.
2. Scans every note for entity mentions (exact string match on canonical name and declared aliases).
3. Groups hits by wing.
4. Writes each `_entity_{slug}.md` with the updated reference list.

Existing corridor files are overwritten. This is safe because corridors are generated artifacts — the source of truth is the note bodies.

Orphan corridors (entities in the manifest with zero references) are NOT deleted. They persist with a "no references" body and log to the morning brief as candidates for manifest cleanup.

### Step 3: Supersession scan

Any note with `superseded_by: {path}` in its frontmatter is flagged. The pass:

1. Finds all notes whose `## Referenced By` section points to the superseded note.
2. Adds a new line `- (superseded → [[{new_path}|{new_title}]])` beneath each pointer.
3. Does NOT remove the old pointer (preserves history).

Humans finalize the redirect by manually editing the source notes. The pass surfaces the candidates; it does not force the rewrite.

### Step 4: Dedup pass

`layer0/dedup.py` hashes every note's body (frontmatter stripped, whitespace normalized). Collisions get logged:

```
# _kks/{date}_dedup_report.md
## Duplicates detected (3)

### Group 1 (hash: a1b2c3...)
- claude/2026-03-10_notes_on_graphify.md (oldest)
- claude/2026-03-14_notes_on_graphify.md
- claude/2026-04-02_notes_on_graphify.md (newest)

Proposed action: mark older notes superseded_by newest, keep all files.
```

Nothing is deleted. The human reviews the report and runs `mymory dedup --apply <group_id>` to execute the supersession.

### Step 5: Morning brief

Output lands at `_kks/{YYYY-MM-DD}_kasai_morning_brief_{HHMM}.md`. Sections:

```markdown
# Morning Brief — 2026-04-21 05:30

## New since last brief (12)
- [[claude/2026-04-20_...|...]]
- ...

## Open items by wing
### Strands (4)
- [[strands/2026-04-18_...|...]] — blockers: ...
### Claude (2)
- ...

## Entity gaps
These entities appeared in notes but have no corridor yet:
- EWDS (3 notes)
- Xendit (2 notes)
Run `mymory entities add EWDS` to create.

## Alias candidates
These entities co-occur in ≥80% of their notes. Consider aliasing:
- "Lemon Squeezy" ↔ "LemonSqueezy" (5/5 co-occur)

## Hygiene stats
- Re-embedded: 8 notes
- Corridors rebuilt: 147
- Duplicates found: 1 group of 3
- Supersession pointers updated: 0

## Unembedded (alert)
- 0 notes older than 24h without an embedding
```

The brief is the single file Sean (or any operator) reads each morning. It should be <200 lines on a healthy vault.

## Running on Windows

Scheduled task setup:

```powershell
# One-time setup, run once as user
$action = New-ScheduledTaskAction -Execute "py" -Argument '-3 "C:\Users\MAG MSI\Project Mymory\scripts\hygiene.py"'
$trigger = New-ScheduledTaskTrigger -Daily -At 05:30
Register-ScheduledTask -TaskName "MyMory Hygiene" -Action $action -Trigger $trigger -Description "Daily vault hygiene pass"
```

To test once without waiting:

```powershell
Start-ScheduledTask -TaskName "MyMory Hygiene"
```

Output writes to vault's `_kks/` plus an append to `.embed_cache/embed_log.jsonl`.

## Running on macOS / Linux

Launchd (macOS) plist at `~/Library/LaunchAgents/com.mymory.hygiene.plist`:

```xml
<plist version="1.0">
<dict>
    <key>Label</key><string>com.mymory.hygiene</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/path/to/mymory/scripts/hygiene.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>30</integer></dict>
</dict>
</plist>
```

Cron (Linux):

```
30 5 * * * /usr/bin/python3 /path/to/mymory/scripts/hygiene.py
```

## Configuration reference

```yaml
# kks_manifest.yaml
hygiene:
  schedule: "05:30"
  enabled: true

  embed:
    enabled: true
    model: "sentence-transformers/all-MiniLM-L6-v2"
    dim: 384
    store: "pickle"

  corridors:
    enabled: true
    min_references: 1              # skip entities with fewer hits

  supersession:
    enabled: true
    auto_redirect: false           # never auto-rewrite; log only

  dedup:
    enabled: true
    hash_algo: "sha256"
    auto_apply: false              # always require human confirm

  brief:
    enabled: true
    path: "_kks/"
    top_k_new: 20
    top_k_open: 10
```

## Failure modes

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Model download fails (first run) | Hygiene hangs on first embed | Run `py -3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"` manually with network |
| Pickle corruption | Embed cache unreadable | Delete `.embed_cache/embeddings.pkl`, next run re-embeds everything (slow but safe) |
| Corridor file mangled | Backlinks don't render | Re-run `mymory hygiene --only corridors` |
| Schedule did not fire | No new brief this morning | Check task scheduler logs; run manually; verify Python path |

## What hygiene does NOT do

- Does not delete files. Ever. Without explicit `--apply` + group id on dedup.
- Does not modify note bodies. Only corridors and embed cache are overwritten.
- Does not auto-alias entities. It proposes; humans confirm.
- Does not prune old notes by age. If you want rotation, that's a separate policy.
- Does not sync across machines. The vault is local. Use file sync (Syncthing, Resilio, iCloud Drive) if needed.

---

Related: `docs/ARCHITECTURE.md` | `docs/TAXONOMY.md` | `README.md`
