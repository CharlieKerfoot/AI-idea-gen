# Idea Engine

A multi-agent system that reads your notes and ideas (Obsidian vault), generates novel essay and startup ideas, judges them with independent agents (to prevent self-censorship bias), writes approved essays back into your vault, and scaffolds minimal experiments for viable startup ideas.

The engine includes three anti-convergence mechanisms — entropy injection, novelty decay, and temporal isolation — to prevent the system from drifting toward repetitive "AI slop" over repeated runs.

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
   ┌──────────────┐ ┌─────────────────────────────────────┐
   │   ENTROPY    │ │            VAULT MANAGER             │
   │  INJECTION   │ │    (reads/writes Obsidian markdown)  │
   │ (Wikipedia,  │ └─────────────────────────────────────┘
   │  arXiv)      │       │                     │
   └──────────────┘       ▼                     ▼
                    ~/obsidian-vault/      ~/dev/experiments/
                    └── _idea-engine/      └── {slug}/
                        ├── essays/            ├── pyproject.toml
                        ├── startups/          ├── src/main.py
                        └── rejected/          └── results.png
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...           # Optional — for council mode
GOOGLE_API_KEY=...              # Optional — for council mode
```

Edit `config.yaml` and set `vault.path` to your Obsidian vault location.

## Usage

```bash
# Single run — generate, judge, and write to vault
python main.py

# Preview what would happen without writing anything
python main.py --dry-run

# Generate ideas without judging them
python main.py --generate-only

# Only evaluate pending startup experiments
python main.py --eval-experiments

# Run continuously on a schedule (default: every 60 minutes)
python main.py --daemon
```

## How It Works

Each run follows this pipeline:

1. **Evaluate due experiments** — If any scaffolded startup experiments have passed their evaluation window, Agent 3 (Mode C) reviews them with a fresh, unbiased LLM call.

2. **Temporal isolation** — The run counter increments and expired quarantines are released. Notes written by recent runs are excluded from vault context to prevent the engine from feeding on its own output.

3. **Scan vault** — Reads your Obsidian notes, selects a mix of recent and random notes as context (configurable via `context_selection` in config). Quarantined note paths are excluded.

4. **Entropy injection** — An external concept is fetched from Wikipedia or arXiv and injected into the generator prompt as a hard constraint. This forces at least one idea to engage with a concept from outside the vault's usual territory.

5. **Novelty decay** — Concepts that have appeared too frequently across previous runs are identified and passed to both the generator (to avoid them) and the judges (to penalize them in scoring).

6. **Generate ideas** (Agent 1) — Reads the vault context, entropy concept, and overused concept list, then generates essay ideas and startup ideas. The generator is explicitly instructed to be maximally creative with no self-censoring. Previously generated titles are excluded to prevent repetition.

7. **Judge essay ideas** (Agent 2) — Each essay idea is scored independently on novelty, interest, and argument quality. The judge never sees the generator's self-assessed connections (blind evaluation). Novelty decay penalties are applied to ideas reusing overused concepts. Ideas scoring above the threshold (default 6.5/10) are written to `_idea-engine/essays/` in your vault and quarantined from future context.

8. **Judge startup ideas** (Agent 3, Mode A) — Each startup idea is scored on problem acuity, insight, tractability, and market signal. Novelty decay penalties apply to `insight_non_obviousness`. Viable ideas (default threshold 6.0/10) proceed to experiment scaffolding.

9. **Scaffold experiments** (Agent 3, Mode B) — For viable startups, a self-contained experiment project is generated at `~/dev/experiments/{slug}/` with a `pyproject.toml`, README, evaluation criteria, implementation code, and a required evidence chart (`results.png`). The experiment is queued for evaluation after 24 hours. Each experiment is a uv-managed Python project — setup is just `uv sync` then `uv run src/main.py`.

## Anti-Convergence

Three mechanisms prevent the engine from narrowing over time:

### Entropy Injection

Each run fetches an external concept and injects it into the generator prompt as a hard constraint. Three strategies are available (configured via `entropy.strategy`):

| Strategy | How it works |
|----------|-------------|
| **`curated_random`** | Picks a random Wikipedia article from curated pools across domains (mathematics, evolutionary biology, architecture, linguistics, economic history, legal theory, physics, music, global history) |
| **`arxiv_rotation`** | Cycles through arXiv categories by day of week (Monday=math, Tuesday=q-bio, etc.) and fetches a recent paper |
| **`adjacent_possible`** | Detects what your vault is dense with via tag frequency, then injects from an adjacent-but-different domain |

All fetches use stdlib (`urllib` + `xml.etree`) with timeouts. Failures are logged and the run continues without entropy.

### Novelty Decay

Keywords are extracted from every generated idea and their frequencies are tracked in persistent state. When a concept crosses the threshold (default: 3 appearances), it is:

- Passed to the generator with instructions to avoid it
- Used to penalize the `novelty_general` (essays) or `insight_non_obviousness` (startups) score during judging, potentially flipping a "keep" to "reject"

### Temporal Isolation

Approved essays and startup notes are quarantined for a configurable number of run cycles (default: 3). During quarantine, the note is excluded from vault context selection, preventing the engine from building on its own recent output and creating a feedback loop.

## Experiments

Scaffolded experiments are self-contained uv-managed Python projects. Each experiment:

- Has a `pyproject.toml` with only the dependencies it needs
- Is one of five types: `cli_script`, `html_prototype`, `api_stub`, `data_analysis`, or `llm_pipeline`
- Generates a `results.png` evidence chart that visually demonstrates whether the hypothesis passed or failed
- Can be run with:

```bash
cd ~/dev/experiments/{slug}
uv sync
uv run src/main.py
```

After the evaluation window (24h), the engine re-evaluates the experiment with a fresh LLM call and recommends `promote`, `iterate`, or `scrap`.

## Agents

| Agent | Role | Key Design Choice |
|-------|------|-------------------|
| **Generator** | Produce raw ideas from vault context | Forbidden from self-censoring; integrates entropy concepts; avoids overused concepts |
| **Essay Judge** | Score and filter essay ideas | Blind evaluation; recomputes scores independently; applies novelty decay penalties |
| **Startup Judge** | Evaluate viability, scaffold experiments, evaluate results | Three modes (judge → scaffold → evaluate) with separate LLM calls; applies novelty decay to insight scores |

## Council Mode

When `essay_judge_council: true` in config, essay ideas are judged by multiple LLMs in parallel (Claude, GPT-4o, Gemini). Scores are averaged across providers, and the verdict requires majority agreement. Missing API keys are handled gracefully — the provider is skipped silently.

## Config

All scoring weights, thresholds, and anti-convergence settings live in `config.yaml`:

```yaml
engine:
  quarantine_cycles: 3            # Runs before a quarantined note is released

thresholds:
  essay_min_score: 6.5            # Minimum weighted score to approve an essay
  novelty_decay_threshold: 3      # Concept appearances before penalty kicks in
  novelty_decay_penalty: 0.3      # Score penalty per excess appearance
  essay_weights:
    novelty_general: 0.3
    novelty_vs_vault: 0.2
    interest: 0.3
    argument_quality: 0.2
  startup_min_viability: 6.0      # Minimum to scaffold an experiment
  startup_weights:
    problem_acuity: 0.25
    insight_non_obviousness: 0.25
    experiment_tractability: 0.30
    market_signal: 0.20

entropy:
  enabled: true
  strategy: "curated_random"      # "curated_random" | "arxiv_rotation" | "adjacent_possible"
  curated_random:
    domains: [mathematics, evolutionary_biology, architecture, linguistics, economic_history, ...]
  arxiv_rotation:
    schedule: {0: math, 1: q-bio, 2: cs.AI, 3: econ, 4: physics.soc-ph, 5: stat.ML, 6: cond-mat}
  adjacent_possible:
    fallback_domain: "mathematics"
```

## Project Structure

```
idea-gen/
├── main.py                  # Orchestrator + CLI
├── config.yaml              # All settings
├── agents/
│   ├── generator.py         # Agent 1: Idea generation
│   ├── essay_judge.py       # Agent 2: Essay scoring + novelty decay
│   └── startup_judge.py     # Agent 3: Startup eval + experiments + novelty decay
├── core/
│   ├── __init__.py          # load_prompt() utility
│   ├── vault.py             # Obsidian vault reader/writer (with quarantine exclusion)
│   ├── state.py             # Persistent state: run history, concept frequencies, quarantine
│   ├── llm.py               # Multi-provider LLM client
│   ├── experiment.py        # Experiment scaffolder (generates pyproject.toml)
│   └── entropy.py           # Entropy injection: Wikipedia/arXiv fetchers, domain pools
├── prompts/                 # System prompts (editable without touching code)
│   ├── generator.md
│   ├── essay_judge.md
│   ├── startup_judge.md
│   └── experiment_eval.md
└── tests/
    ├── fake_vault/          # 15 sample notes for testing
    ├── test_vault.py
    ├── test_state.py        # State, concept tracking, quarantine lifecycle, keyword extraction
    ├── test_llm.py
    └── test_entropy.py      # Entropy strategies, domain pools, mocked API calls
```

## Tests

```bash
pytest tests/ -v
```

Tests run against a fake vault with no API keys required. They cover vault scanning/exclusion, atomic writes, state persistence, JSON extraction, council mode aggregation, keyword extraction, concept frequency tracking, quarantine lifecycle, entropy strategy dispatch, and mocked Wikipedia/arXiv API calls.
