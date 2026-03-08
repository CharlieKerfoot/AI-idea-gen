# Idea Engine

A multi-agent system that reads your notes and ideas (Obsidian vault), generates novel essay and startup ideas, judges them with independent agents (to prevent self-censorship bias), writes approved essays back into your vault, and scaffolds minimal experiments for viable startup ideas.

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
       └── rejected/         ← rejected with reasoning
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

2. **Scan vault** — Reads your Obsidian notes, selects a mix of recent and random notes as context (configurable via `context_selection` in config).

3. **Generate ideas** (Agent 1) — Reads the vault context and generates essay ideas and startup ideas. The generator is explicitly instructed to be maximally creative with no self-censoring. Previously generated titles are excluded to prevent repetition.

4. **Judge essay ideas** (Agent 2) — Each essay idea is scored independently on novelty, interest, and argument quality. The judge never sees the generator's self-assessed connections (blind evaluation). Ideas scoring above the threshold (default 6.5/10) are written to `_idea-engine/essays/` in your vault.

5. **Judge startup ideas** (Agent 3, Mode A) — Each startup idea is scored on problem acuity, insight, tractability, and market signal. Viable ideas (default threshold 6.0/10) proceed to experiment scaffolding.

6. **Scaffold experiments** (Agent 3, Mode B) — For viable startups, a minimal experiment is generated at `~/dev/experiments/{slug}/` with a README, evaluation criteria, and implementation code. The experiment is queued for evaluation after 24 hours.

## Agents

| Agent | Role | Key Design Choice |
|-------|------|-------------------|
| **Generator** | Produce raw ideas from vault context | Forbidden from self-censoring; novelty weighted highest |
| **Essay Judge** | Score and filter essay ideas | Blind evaluation; recomputes scores independently (doesn't trust LLM's math) |
| **Startup Judge** | Evaluate viability, scaffold experiments, evaluate results | Three modes (judge → scaffold → evaluate) with separate LLM calls to prevent bias |

## Council Mode

When `essay_judge_council: true` in config, essay ideas are judged by multiple LLMs in parallel (Claude, GPT-4o, Gemini). Scores are averaged across providers, and the verdict requires majority agreement. Missing API keys are handled gracefully — the provider is skipped silently.

## Config

All scoring weights and thresholds live in `config.yaml`:

```yaml
thresholds:
  essay_min_score: 6.5          # Minimum weighted score to approve an essay
  essay_weights:
    novelty_general: 0.3
    novelty_vs_vault: 0.2
    interest: 0.3
    argument_quality: 0.2
  startup_min_viability: 6.0    # Minimum to scaffold an experiment
  startup_weights:
    problem_acuity: 0.25
    insight_non_obviousness: 0.25
    experiment_tractability: 0.30
    market_signal: 0.20
```

## Project Structure

```
idea-gen/
├── main.py                  # Orchestrator + CLI
├── config.yaml              # All settings
├── agents/
│   ├── generator.py         # Agent 1: Idea generation
│   ├── essay_judge.py       # Agent 2: Essay scoring
│   └── startup_judge.py     # Agent 3: Startup eval + experiments
├── core/
│   ├── __init__.py          # load_prompt() utility
│   ├── vault.py             # Obsidian vault reader/writer
│   ├── state.py             # Persistent state (JSON)
│   ├── llm.py               # Multi-provider LLM client
│   └── experiment.py        # Experiment scaffolder
├── prompts/                 # System prompts (editable without touching code)
│   ├── generator.md
│   ├── essay_judge.md
│   ├── startup_judge.md
│   └── experiment_eval.md
└── tests/
    ├── fake_vault/          # 15 sample notes for testing
    ├── test_vault.py
    ├── test_state.py
    └── test_llm.py
```

## Tests

```bash
pytest tests/ -v
```

Tests run against a fake vault with no API keys required. They cover vault scanning/exclusion, atomic writes, state persistence, JSON extraction, and council mode aggregation.
