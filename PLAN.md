# Obsidian Idea Engine — Full Implementation Plan

## Context

The user wants to build a complete multi-agent autonomous system from scratch. The codebase contains only `BLUEPRINT.md`. The system reads an Obsidian vault, generates novel essay ideas and startup ideas via an LLM generator agent, passes them through independent judge agents (to prevent self-censorship bias), writes approved essay ideas back into the vault as Obsidian notes, and scaffolds minimal experiments for viable startup ideas into a dev folder.

**User preferences:**
- Default model: `claude-opus-4-6`
- Vault path: "~/Obsidian/The Simple Soul/"
- Build scope: full system in one session
- Council mode: implement multi-LLM voting, default `false`, non-Anthropic keys are optional

---

## Final Directory Structure

```
idea-gen/
├── main.py
├── config.yaml
├── requirements.txt
├── .env.example
├── agents/
│   ├── __init__.py
│   ├── generator.py
│   ├── essay_judge.py
│   └── startup_judge.py
├── core/
│   ├── __init__.py          ← load_prompt() utility here
│   ├── vault.py
│   ├── state.py
│   ├── llm.py
│   └── experiment.py
├── prompts/
│   ├── generator.md
│   ├── essay_judge.md
│   ├── startup_judge.md
│   └── experiment_eval.md
└── tests/
    ├── fake_vault/          ← 15 sample notes across 5 topic dirs
    ├── test_vault.py
    ├── test_state.py
    └── test_llm.py
```

---

## Implementation Order

### Phase 0 — Scaffolding

**Files:** `requirements.txt`, `.env.example`, `config.yaml`, `agents/__init__.py`, `core/__init__.py`

**`requirements.txt`:**
```
anthropic>=0.40.0
openai>=1.30.0
google-generativeai>=0.8.0
pyyaml>=6.0
pydantic>=2.7.0
python-frontmatter>=1.1.0
schedule>=1.2.0
rich>=13.7.0
click>=8.1.0
python-dotenv>=1.0.0
tenacity>=8.2.0
```

**`config.yaml`:** All models default to `claude-opus-4-6`. Scoring weights live in config (not hardcoded in agents):
```yaml
thresholds:
  essay_min_score: 6.5
  essay_weights:
    novelty_general: 0.3
    novelty_vs_vault: 0.2
    interest: 0.3
    argument_quality: 0.2
  startup_min_viability: 6.0
  startup_weights:
    problem_acuity: 0.25
    insight_non_obviousness: 0.25
    experiment_tractability: 0.30
    market_signal: 0.20
  experiment_success_threshold: 6.0
```

---

### Phase 1 — Foundation: `core/vault.py` + `core/state.py`

**`core/vault.py` — `VaultManager` class:**

Key methods:
- `scan_notes() -> list[VaultNote]` — walk vault with glob, parse frontmatter via `python-frontmatter`, exclude configured folders
- `select_context_notes(n, strategy) -> list[VaultNote]` — "recent_and_random": top 50% from most-recent notes, rest random
- `write_essay_idea(idea, judgment) -> Path` — atomic write to `vault/_idea-engine/essays/`
- `write_startup_judgment(judgment) -> Path` — atomic write to `vault/_idea-engine/startups/`
- `write_rejection(item) -> Path` — atomic write to `vault/_idea-engine/rejected/`
- `write_experiment_result(result, outcome, new_path) -> Path`
- `_atomic_write(path, content)` — write to `.tmp`, then `tmp.rename(path)` (POSIX atomic)
- `compute_content_hash() -> str` — SHA256 of sorted note filenames + mtimes

**`VaultNote` Pydantic model:** `title, path, content, preview (200 chars), tags, frontmatter, modified_at, word_count`

**Essay note template written to vault:**
```markdown
---
tags: [essay-idea, engine-generated, <suggested_tags>]
date: YYYY-MM-DD
score: 7.35
connections: [note1, note2]
engine_run_id: "run-2026-..."
---

# {title}

**Hook:** {hook}
**Argument:** {argument_sketch}
**Novelty claim:** {novelty_claim}
**Judge reasoning:** {reasoning}
**Improvement note:** {improvement_note}
```

**`core/state.py` — `StateManager` class:**

State file lives at `{vault_path}/.engine-state.json` (NOT inside `_idea-engine/` to avoid being scanned as a vault note).

Key Pydantic models:
```python
class PendingExperiment(BaseModel):
    slug: str; created_at: datetime; eval_after: datetime
    idea_name: str; hypothesis: str; falsification_criteria: str; experiment_path: str

class RunRecord(BaseModel):
    run_id: str; timestamp: datetime; ideas_generated: int
    essays_approved: int; essays_rejected: int
    startups_approved: int; startups_rejected: int; vault_hash: str

class EngineState(BaseModel):
    seen_idea_titles: set[str]
    run_history: list[RunRecord]
    pending_experiments: list[PendingExperiment]
    vault_hash: str; last_run: datetime | None
```

`StateManager.load()`: if file missing → return fresh state. If JSON parse error → log warning, backup corrupt file, return fresh state.
`StateManager.save()`: atomic write (same pattern as vault).
`get_due_experiments()`: filter where `eval_after <= datetime.now()`.

**Write tests immediately** (`tests/test_vault.py`, `tests/test_state.py`) using `tmp_path` pytest fixture.

---

### Phase 2 — Infrastructure: `core/llm.py` + `core/experiment.py`

**`core/llm.py` — `LLMClient` class:**

Provider registry pattern — not hard-coded if/else:
```python
PROVIDER_REGISTRY = {
    "anthropic": (AnthropicProvider, "ANTHROPIC_API_KEY"),
    "openai": (OpenAIProvider, "OPENAI_API_KEY"),
    "google": (GoogleProvider, "GOOGLE_API_KEY"),
}
```

Providers initialized lazily at startup — only if their env key exists. Anthropic is always required.

**Retry logic:** Use `tenacity` decorators with `stop_after_attempt(3)`, `wait_exponential(min=4, max=10)`, retrying on `RateLimitError` and `APITimeoutError`.

**Structured output extraction** (3-tier):
1. Extract from ` ```json ``` ` code fence (Claude's natural format)
2. Parse entire response as raw JSON
3. Balanced-brace finder for JSON embedded in text

On failure: log full prompt + response to `_idea-engine/engine-log.json`, print truncated error via `rich`.

**Council mode** (`council_call()`):
- Dispatches to all available providers in parallel via `ThreadPoolExecutor(max_workers=3)`
- Returns `CouncilResult` with `averaged_scores`, `final_verdict` (majority), `consensus_level`, `dissenting_reasoning`, `providers_skipped`
- Missing key → provider skipped silently at dispatch
- Provider call fails → `CouncilVote.error` populated → counted in `providers_skipped`
- All providers fail → `RuntimeError`

**`core/experiment.py` — `ExperimentScaffolder` class:**

Creates folder at `~/dev/experiments/{slug}/` with:
```
{slug}/
├── README.md           ← hypothesis + setup instructions
├── EVAL_CRITERIA.md    ← explicit pass/fail criteria
├── .engine-meta.json   ← PendingExperiment data for Mode C self-containment
└── src/
    └── {main_file}
```

Slug derived from: `idea.name.lower().replace(" ", "-")`, strip non-alphanumeric, truncate to 40 chars.

`promote_experiment(slug)`: move folder from `~/dev/experiments/` to `~/dev/projects/`.

**`ExperimentScaffold` Pydantic model:**
```python
class ExperimentFile(BaseModel):
    filename: str; content: str

class ExperimentScaffold(BaseModel):
    experiment_type: Literal["cli_script", "html_prototype", "api_stub", "data_analysis", "llm_pipeline"]
    slug: str; readme_content: str; eval_criteria_content: str
    implementation_files: list[ExperimentFile]
```

---

### Phase 3 — Prompts (`prompts/*.md`)

All prompts loaded at agent instantiation via `core.load_prompt(name)`. The utility resolves paths relative to `PROJECT_ROOT = Path(__file__).parent.parent`.

**`prompts/generator.md`** — Emphasize:
- Role: "maximally generative, explicitly forbidden from self-censoring"
- Weight novelty; prefer "uncomfortable" or contrarian essay angles
- `connections` must reference actual provided note titles (not invented)
- `experiment_hypothesis` must use exact IF/THEN format
- `falsification_criteria` must be concrete — no weasel words
- Full JSON schema verbatim in prompt (wrapped in ` ```json ``` ` fence)
- Anti-repetition: include seen titles list in user message

**`prompts/essay_judge.md`** — Emphasize:
- "Ruthless gatekeeper" role, no stake in the ideas
- Blind evaluation: `connections` field from generator NOT passed to judge
- Full scoring rubric with 3/10 / 6/10 / 9/10 example anchors per dimension
- "Be stingy with 'keep'" — 6.5 is minimum, not typical
- Recompute `weighted_score` from raw scores (agent doesn't trust LLM's computed value)

**`prompts/startup_judge.md`** — Used for Mode A and Mode B (user message specifies mode):
- Mode A: score for tractability above all; "worth one weekend to test"
- Mode B: design the simplest experiment to test only the `core_mechanic`
- Experiment type decision tree (cli_script / html_prototype / api_stub / data_analysis / llm_pipeline)
- Code must use only stdlib + common packages (requests, fastapi, pandas)

**`prompts/experiment_eval.md`** — Emphasize:
- "Cold read — you have never seen this experiment before"
- Strict verdict definitions: validated / falsified / inconclusive (last resort)
- Score reflects *quality of evidence*, not whether hypothesis was validated

---

### Phase 4 — Agent 1: `agents/generator.py`

**`GeneratorAgent.generate(vault_notes, seen_titles, n_ideas) -> GeneratorOutput`**

User message format:
```
## Vault Context ({n} notes)
### {title}
{preview 200 chars}
---
## Previously Generated Ideas (do not repeat)
- {title}
...
## Task
Generate {n} essay ideas and {n} startup ideas.
```

Post-generation: filter out any generated titles already in `seen_titles` (guard against model repeating). Add ALL generated titles to state (even those that will be rejected — prevents re-generating).

**Pydantic models:** `EssayIdea`, `StartupIdea`, `GeneratorOutput` (matching blueprint schemas exactly).

---

### Phase 5 — Agent 2: `agents/essay_judge.py`

**`EssayJudgeAgent.judge(idea, vault_notes, council_mode) -> EssayJudgment`**

Critical: agent recomputes `weighted_score` from raw scores using config weights — does NOT trust the LLM's `weighted_score` field. Same for `verdict` — re-applies threshold independently.

Council mode path: calls `llm.council_call()`, populates `EssayJudgment.council_result`. Top-level `verdict` and `weighted_score` derived from `CouncilResult`, not single model.

**`EssayJudgment` Pydantic model:** `idea_title, scores (EssayScores), weighted_score, verdict, reasoning, suggested_vault_tags, improvement_note, council_result`

Note: `connections` from generator is NOT passed to judge (enforces blind evaluation).

---

### Phase 6 — Agent 3: `agents/startup_judge.py`

Three methods on `StartupJudgeAgent`:

**Mode A — `judge_viability(idea) -> StartupJudgment`:**
- Score on 4 dimensions, recompute weighted score from config weights
- If `weighted_score < startup_min_viability`: write rejection to vault

**Mode B — `scaffold_experiment(idea) -> PendingExperiment`:**
- Call LLM with Mode B prompt, parse `ExperimentScaffold`
- Call `scaffolder.create_experiment()` to write files
- Return `PendingExperiment` for state tracking
- `eval_after` = `created_at + timedelta(hours=24)` by default

**Mode C — `evaluate_experiment(pending) -> ExperimentResult`:**
- Fresh LLM call — NO conversation history from Modes A/B
- User message built from experiment folder: `EVAL_CRITERIA.md` + implementation files + `.engine-meta.json`
- On "promote": `scaffolder.promote_experiment()` + write vault note
- On "scrap": write rejection note with learnings preserved
- On "iterate": return iterated idea to orchestrator for re-judging

---

### Phase 7 — Orchestrator: `main.py`

**CLI (click flags, not subcommands — matches blueprint's `python main.py --flag` interface):**
```python
@click.command()
@click.option("--daemon", is_flag=True)
@click.option("--eval-experiments", "eval_experiments", is_flag=True)
@click.option("--generate-only", "generate_only", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--config", default="config.yaml")
def main(daemon, eval_experiments, generate_only, dry_run, config): ...
```

**`validate_config(config)`** (fatal on missing vault path or `ANTHROPIC_API_KEY`; warning on missing council keys):
- Vault path is `PLACEHOLDER_CHANGE_ME` → `SystemExit(1)` with red error
- Vault path does not exist → `SystemExit(1)`
- `ANTHROPIC_API_KEY` not set → `SystemExit(1)`
- Council enabled but OpenAI/Google keys missing → yellow warning, continue

**`run_once()` pseudocode:**
1. Check due experiments → run Mode C for each
2. Scan vault context notes
3. Generate ideas (Agent 1)
4. Judge each essay idea (Agent 2) → write to vault if approved
5. Judge each startup idea (Agent 3 Mode A) → scaffold if viable (Mode B)
6. Save state

**`rich` output:** `console.rule()` for section headers, `Table` for judgment results (color-coded verdict column: green=keep/viable, red=reject), `console.status()` spinners during LLM calls, `Panel` for approved ideas.

**Daemon mode:** `schedule.every(interval).minutes.do(run_once, ...)`, run immediately on start, then `while True: schedule.run_pending(); time.sleep(30)`.

---

### Phase 8 — Tests + Fake Vault

**`tests/fake_vault/`** — 15 notes across 5 dirs with real, contestable content:
```
Technology & AI/  (LLMs-are-not-reasoning.md, Attention-mechanism-intuition.md, Software-eating-the-world-revisited.md)
Philosophy/       (Free-will-as-useful-fiction.md, The-hard-problem-is-unsolvable.md, Epistemology-of-intuition.md)
Economics/        (Markets-as-information-systems.md, Incentive-blindness.md, Rent-seeking-in-academia.md)
Writing & Ideas/  (Why-outlines-kill-essays.md, The-curse-of-knowledge.md, Ideas-want-to-be-free.md)
Personal/         (On-boredom-and-creativity.md, Procrastination-as-signal.md)
Startups/         (The-missionary-vs-mercenary-founder.md)
```

Each note: YAML frontmatter (tags, date), H1 title, 150-300 words of real ideas, at least one wikilink.

**`tests/test_vault.py`:** 9 tests covering exclusion, frontmatter parsing, missing frontmatter, atomic write, context selection count, recent-and-random strategy, content hash, essay note frontmatter correctness.

**`tests/test_state.py`:** 4 tests covering fresh state creation, persistence across load/save, due experiment filtering, title deduplication.

**`tests/test_llm.py`:** 5 mock-based tests covering JSON extraction from code fence, raw JSON fallback, council skipping unavailable provider, council majority verdict, retry on rate limit.

---

## Critical Files

- `BLUEPRINT.md` — source of truth for schemas and weights; cross-reference during implementation
- `core/llm.py` — most complex; council mode + retry + structured output extraction
- `core/vault.py` — foundation; atomic writes + exclusion logic must be solid first
- `core/state.py` — persistence layer; `PendingExperiment` + `get_due_experiments()` gates Mode C
- `main.py` — integration surface; `validate_config()` + `run_once()` + CLI

---

## Verification Steps

1. **Unit tests (no API keys needed):** `pytest tests/` against fake vault
2. **Dry-run:** point config at `tests/fake_vault/`, run `python main.py --dry-run` — verify rich output, no files written
3. **Single real run:** `python main.py` — inspect `.engine-state.json` and `_idea-engine/` output notes
4. **Council mode test:** enable council with only `ANTHROPIC_API_KEY`, run `--dry-run` — verify skipped providers logged, no crash
5. **Daemon test:** set `run_interval_minutes: 1`, run `--daemon` — verify two runs complete, seen titles exclude first run's ideas
6. **Experiment eval test:** manually add a past-due `PendingExperiment` to state, run `--eval-experiments` — verify Mode C runs and experiment removed from state
