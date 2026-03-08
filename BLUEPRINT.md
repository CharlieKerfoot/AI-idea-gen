# Obsidian Idea Engine — Claude Code Build Plan

A multi-agent autonomous system that reads your Obsidian vault, synthesizes novel ideas, judges them with independent agents, and either writes essay ideas back into the vault or scaffolds startup experiments into your dev folder.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                             │
│              (scheduler + state machine + logging)              │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐
   │  AGENT 1    │ │   AGENT 2    │ │    AGENT 3       │
   │  Generator  │ │ Essay Judge  │ │  Startup Judge   │
   │  (Claude)   │ │  (Claude or  │ │  + Experiment    │
   │             │ │  Council)    │ │  Builder         │
   └─────────────┘ └──────────────┘ └──────────────────┘
          │              │                    │
          ▼              ▼                    ▼
   ┌─────────────────────────────────────────────────────┐
   │                   VAULT MANAGER                     │
   │        (reads/writes Obsidian markdown files)       │
   └─────────────────────────────────────────────────────┘
          │                                   │
          ▼                                   ▼
   ~/obsidian-vault/                    ~/dev/experiments/
   └── _idea-engine/
       ├── essays/           ← approved essay ideas
       ├── startups/         ← startup judgments
       ├── rejected/         ← rejected with reasoning
       └── engine-log.json   ← full run history
```

---

## Directory Structure

```
obsidian-idea-engine/
├── main.py                  # Orchestrator / entry point
├── config.yaml              # All user-configurable settings
├── agents/
│   ├── __init__.py
│   ├── generator.py         # Agent 1: Idea Generator
│   ├── essay_judge.py       # Agent 2: Essay Judge
│   └── startup_judge.py     # Agent 3: Startup Judge + Experiment Builder
├── core/
│   ├── __init__.py
│   ├── vault.py             # Obsidian vault reader/writer
│   ├── state.py             # Persistent state (seen ideas, run history)
│   ├── llm.py               # LLM client abstraction (Anthropic + others)
│   └── experiment.py        # Experiment scaffolder
├── prompts/
│   ├── generator.md         # Generator system prompt
│   ├── essay_judge.md       # Essay judge system prompt
│   ├── startup_judge.md     # Startup judge system prompt
│   └── experiment_eval.md   # Experiment evaluator system prompt
├── requirements.txt
├── .env.example
└── README.md
```

---

## config.yaml

```yaml
vault:
  path: "~/Obsidian/The\ Simple\ Soul"          # Path to your Obsidian vault
  idea_engine_folder: "_idea-engine"          # Subfolder for engine outputs
  scan_glob: "**/*.md"                        # Which files to read
  exclude_folders:                            # Folders to skip
    - "_idea-engine"
    - "templates"
    - ".obsidian"

dev:
  experiments_path: "~/dev/idea-gen/experiments"       # Where to scaffold startup experiments
  approved_path: "~/dev/idea-gen/projects"             # Where to move successful experiments

engine:
  run_interval_minutes: 60                    # How often the loop runs
  ideas_per_run: 3                            # How many ideas to generate per cycle
  max_vault_context_notes: 30                 # Max notes to pass as context
  context_selection: "recent_and_random"      # "recent", "random", "semantic" (future)

agents:
  generator_model: "claude-opus-4-6"          # Most creative model for generation
  essay_judge_model: "claude-opus-4-6"        # Can swap for different provider
  startup_judge_model: "claude-opus-4-6"
  experiment_eval_model: "claude-opus-4-6"

  # For unbiased judging: set use_council: true to run multiple models
  # and aggregate scores. Requires additional API keys.
  essay_judge_council: false
  council_models:                             # Used if essay_judge_council: true
    - provider: "anthropic"
      model: "claude-opus-4-6"
    - provider: "openai"
      model: "gpt-4o"
    - provider: "google"
      model: "gemini-1.5-pro"

thresholds:
  essay_min_score: 6.5                        # Out of 10 to be written to vault
  novelty_weight: 0.5                         # Novelty's share of final essay score
  interest_weight: 0.3
  quality_weight: 0.2
  startup_min_viability: 6.0                  # Out of 10 to scaffold experiment
  experiment_success_threshold: 6.0           # Out of 10 to promote to dev/projects
```

---

## Agent 1 — Generator (`agents/generator.py`)

**Purpose:** Read vault context, generate a batch of raw ideas in both categories.

**Inputs:**
- A randomly sampled set of vault notes (titles + first 200 chars, or full content for shorter notes)
- A list of previously generated idea titles (to avoid repetition)
- The count of desired ideas

**Output schema (JSON):**
```json
{
  "essay_ideas": [
    {
      "title": "string",
      "hook": "one sentence — the surprising or counterintuitive claim",
      "argument_sketch": "2-3 sentences on the core argument",
      "connections": ["note-title-1", "note-title-2"],
      "novelty_claim": "why this angle hasn't been done to death"
    }
  ],
  "startup_ideas": [
    {
      "name": "string",
      "problem": "specific problem being solved",
      "insight": "non-obvious insight that makes this viable",
      "target_user": "string",
      "core_mechanic": "the one thing the experiment needs to validate",
      "experiment_hypothesis": "IF [mechanic] THEN [measurable outcome]",
      "falsification_criteria": "what would make us scrap this"
    }
  ]
}
```

**System prompt highlights** (`prompts/generator.md`):
- Explicitly instructed to weight novelty highest
- Told to find non-obvious connections between vault notes
- Forbidden from generating ideas that closely match existing vault titles
- Instructed to prefer "uncomfortable" or "contrarian" angles for essays

---

## Agent 2 — Essay Judge (`agents/essay_judge.py`)

**Purpose:** Score each essay idea independently, decide keep/reject.

**Design principle:** Agent 2 never sees Agent 1's self-assessment of novelty. It receives only the idea itself and the vault context, and scores blind.

**Scoring rubric (out of 10 each):**
| Dimension | Weight | Description |
|---|---|---|
| Novelty (general) | 0.3 | Is this angle genuinely fresh in the world? |
| Novelty (vs vault) | 0.2 | Does this meaningfully extend or contradict existing notes? |
| Interest | 0.3 | Would a thoughtful reader be compelled to read this? |
| Argument quality | 0.2 | Is the core claim defensible and specific? |

**Final score** = weighted sum. If ≥ threshold in config, idea is approved.

**Output schema:**
```json
{
  "idea_title": "string",
  "scores": {
    "novelty_general": 7.5,
    "novelty_vs_vault": 8.0,
    "interest": 6.5,
    "argument_quality": 7.0
  },
  "weighted_score": 7.35,
  "verdict": "keep" | "reject",
  "reasoning": "2-3 sentences",
  "suggested_vault_tags": ["#essay-idea", "#philosophy"],
  "improvement_note": "optional — what would make this stronger"
}
```

**Council mode** (if `essay_judge_council: true`):
- Same prompt sent to Claude, GPT-4o, Gemini independently
- Scores averaged per dimension
- Verdict requires majority agreement (≥ 2/3 models say "keep")
- Dissenting reasoning is preserved in the log

**On approval:** Agent 2 writes a markdown file to `vault/_idea-engine/essays/`:
```markdown
---
tags: [essay-idea, engine-generated]
date: 2025-03-08
score: 7.35
connections: [note1, note2]
---

# [Title]

**Hook:** ...
**Argument:** ...
**Novelty claim:** ...
**Judge reasoning:** ...
```

---

## Agent 3 — Startup Judge + Experiment Builder (`agents/startup_judge.py`)

**Purpose:** Evaluate startup ideas for viability, scaffold experiments for viable ones, evaluate experiment results.

This agent has **three modes** called sequentially:

### Mode A — Viability Judge
Scores the raw startup idea before any code is written.

**Scoring rubric:**
| Dimension | Weight |
|---|---|
| Problem acuity | 0.25 |
| Insight non-obviousness | 0.25 |
| Experiment tractability | 0.3 |
| Market signal | 0.2 |

If score ≥ `startup_min_viability`: proceed to Mode B.
If below: write rejection note to `vault/_idea-engine/startups/rejected/`.

### Mode B — Experiment Scaffolder
Generates a minimal experiment. The experiment should test **only** the `core_mechanic` — nothing else.

**Experiment types** (Agent 3 picks the appropriate one):
- `cli_script` — a Python CLI tool that demonstrates the core value
- `html_prototype` — a single-file HTML/JS mockup
- `api_stub` — a FastAPI endpoint that simulates the service
- `data_analysis` — a Jupyter notebook that validates a data-driven assumption
- `llm_pipeline` — a prompt chain that demonstrates an AI-powered workflow

Agent 3 outputs:
1. A folder scaffold at `~/dev/experiments/[idea-slug]/`
2. A `README.md` with the hypothesis and how to evaluate it
3. The minimal implementation code
4. An `EVAL_CRITERIA.md` with explicit pass/fail criteria

### Mode C — Experiment Evaluator
After a configurable delay (default: 24 hours, or triggered manually), Agent 3 re-reads the experiment folder and evaluates it against `EVAL_CRITERIA.md`.

**This is the unbiased evaluation:** A *separate* Claude call with no memory of having built the experiment. It receives only:
- The original hypothesis
- The falsification criteria
- The experiment code/output

**Output:**
```json
{
  "experiment_slug": "string",
  "hypothesis_verdict": "validated" | "falsified" | "inconclusive",
  "score": 7.2,
  "evidence": "what specifically supports or contradicts the hypothesis",
  "recommendation": "promote" | "scrap" | "iterate",
  "iteration_suggestion": "optional — what to change if iterating"
}
```

**On "promote":** Moves folder to `~/dev/projects/[idea-slug]/` and writes a note to vault.
**On "scrap":** Writes a rich rejection note to `vault/_idea-engine/startups/rejected/` (preserving the learnings).
**On "iterate":** Re-queues with Agent 3 Mode B using the iteration suggestion.

---

## Core Modules

### `core/vault.py`
```python
# Key responsibilities:
# - Walk vault directory, parse frontmatter + content
# - Select context notes (recent + random sampling)
# - Write new notes atomically (tmp file → rename)
# - Never touch notes outside _idea-engine/ unless config says otherwise
# - Track which notes have been used as context (for diversity)
```

### `core/state.py`
```python
# Persistent JSON state file: .engine-state.json in vault root
# Tracks:
# - All generated idea titles (to prevent repeats)
# - Run history (timestamp, ideas generated, verdicts)
# - Pending experiment evaluations (queued for Mode C)
# - Vault content hash (to detect when new notes are added)
```

### `core/llm.py`
```python
# Abstraction over multiple LLM providers
# Supports: Anthropic, OpenAI, Google Gemini
# All calls are logged with token counts
# Retry logic with exponential backoff
# Structured output validation (pydantic models for each agent's schema)
```

### `core/experiment.py`
```python
# Handles filesystem ops for experiments:
# - Create experiment folder structure
# - Write scaffolded files
# - Read experiment outputs for evaluation
# - Promote / archive experiments
```

---

## `main.py` — Orchestrator Loop

```python
"""
Pseudocode for main loop:

1. Load config + state
2. Scan vault, build context
3. Check for pending experiment evaluations → run Agent 3 Mode C if due
4. Run Agent 1 → get raw idea batch
5. For each essay idea → run Agent 2 → write to vault if approved
6. For each startup idea → run Agent 3 Mode A → scaffold if viable
7. Save state
8. Sleep until next interval
"""
```

**Running modes:**
```bash
python main.py                    # Run once and exit
python main.py --daemon           # Run indefinitely on schedule
python main.py --eval-experiments # Only run pending experiment evals
python main.py --generate-only    # Only generate, skip judging
python main.py --dry-run          # Print what would happen, write nothing
```

---

## requirements.txt

```
anthropic>=0.25.0
openai>=1.30.0          # Optional, for council mode
google-generativeai     # Optional, for council mode
pyyaml>=6.0
pydantic>=2.0
python-frontmatter>=1.0
schedule>=1.2
rich>=13.0              # Nice CLI output
click>=8.1
python-dotenv>=1.0
```

---

## .env.example

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...           # Optional
GOOGLE_API_KEY=...              # Optional
```

---

## Key Design Decisions & Rationale

### Why separate generator from judge?
The generator is instructed to be maximally creative and generative — no filter. The judge is explicitly told it has no stake in the ideas and should be ruthless. Keeping them separate prevents the generator from self-censoring.

### Why is novelty weighted so heavily?
Ideas that are *interesting but not novel* are everywhere. The vault already has them. The only ideas worth adding to the loop are ones that genuinely expand the solution space — which means novelty vs. the existing vault is the most important signal.

### Why use a separate LLM call for experiment evaluation?
The same model that built the experiment has implicit bias toward validating its own work. Mode C is a cold read — no prior context — which is the closest approximation to an unbiased external reviewer.

### Why not use semantic search for vault context?
Deliberate decision for v1: random + recency sampling forces the generator to make unexpected connections. Semantic similarity would create an echo chamber where related ideas only ever spawn more related ideas. This can be added as a config option later.

### Why flat JSON state instead of a database?
Obsidian vaults are file-first. A SQLite database or vector store would add dependencies and complexity. The state file is human-readable, git-committable, and easy to inspect. Switch to SQLite + embeddings in v2 if the vault grows large.

---

## Claude Code Instructions

When implementing this system:

1. **Start with `core/vault.py` and `core/state.py`** — everything depends on these being solid. Write tests for the vault reader before touching agents.

2. **Implement Agent 1 first**, run it with `--dry-run` and inspect the output JSON carefully. Tune the generator prompt before moving on.

3. **Implement Agent 2 next**. The essay judge is simpler than the startup judge and lets you validate the scoring pipeline end-to-end.

4. **Agent 3 Mode A → B → C** in sequence. Mode C is the most complex — defer it until A and B are working.

5. **Use `rich` for all terminal output** — this will run as a daemon and the logs need to be readable at a glance.

6. **All LLM calls must be wrapped in try/except** with the full prompt logged on failure. Silent failures are the enemy of a system like this.

7. **The vault writer must be atomic** — write to a temp file, then rename. Never leave a half-written note.

8. **Prompts live in `/prompts/*.md`**, not hardcoded in Python. This lets you tune them without touching code.

9. **Every run should be fully reproducible from the state file** — if something goes wrong, you need to be able to inspect exactly what happened.

10. **Test with a small fake vault first** (10-15 sample notes) before pointing it at your real vault.
