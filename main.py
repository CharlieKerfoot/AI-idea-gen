"""Obsidian Idea Engine — Orchestrator."""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import schedule
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.essay_judge import EssayJudgeAgent
from agents.generator import GeneratorAgent
from agents.startup_judge import StartupJudgeAgent
from core.entropy import fetch_entropy_concept
from core.experiment import ExperimentScaffolder
from core.llm import LLMClient
from core.state import RunRecord, StateManager
from core.vault import VaultManager

load_dotenv()

console = Console()
logger = logging.getLogger("idea-engine")


# ── Config ───────────────────────────────────────────────────────


def load_config(config_path: str) -> dict:
    """Load and return the YAML config."""
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red bold]Config file not found:[/] {config_path}")
        raise SystemExit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_config(config: dict):
    """Validate config and environment. Fatal on critical issues."""
    vault_path = config["vault"]["path"]

    if vault_path == "PLACEHOLDER_CHANGE_ME":
        console.print(
            "[red bold]Vault path not configured![/]\n"
            "Edit config.yaml and set vault.path to your Obsidian vault."
        )
        raise SystemExit(1)

    expanded = Path(vault_path).expanduser()
    if not expanded.exists():
        console.print(f"[red bold]Vault path does not exist:[/] {expanded}")
        raise SystemExit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[red bold]ANTHROPIC_API_KEY not set![/]\n"
            "Set it in .env or your environment."
        )
        raise SystemExit(1)

    # Council mode warnings
    if config["agents"].get("essay_judge_council", False):
        if not os.environ.get("OPENAI_API_KEY"):
            console.print(
                "[yellow]Council mode enabled but OPENAI_API_KEY not set — "
                "OpenAI provider will be skipped.[/]"
            )
        if not os.environ.get("GOOGLE_API_KEY"):
            console.print(
                "[yellow]Council mode enabled but GOOGLE_API_KEY not set — "
                "Google provider will be skipped.[/]"
            )


# ── Run Logic ────────────────────────────────────────────────────


def run_once(
    config: dict,
    dry_run: bool = False,
    generate_only: bool = False,
    eval_experiments_only: bool = False,
):
    """Execute a single engine run."""
    run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    console.rule(f"[bold blue]Idea Engine Run: {run_id}")

    vault = VaultManager(config)
    state_mgr = StateManager(config["vault"]["path"])
    llm = LLMClient(config)
    scaffolder = ExperimentScaffolder(config)
    quarantine_cycles = config["engine"].get("quarantine_cycles", 3)
    novelty_threshold = config["thresholds"].get("novelty_decay_threshold", 3)

    # Temporal isolation: increment run count and expire old quarantines
    state_mgr.increment_run_count()
    state_mgr.expire_quarantines()

    essays_approved = 0
    essays_rejected = 0
    startups_approved = 0
    startups_rejected = 0
    ideas_generated = 0

    # ── Step 1: Check due experiments ────────────────────────
    if not generate_only:
        due = state_mgr.get_due_experiments()
        if due:
            console.rule("[bold]Evaluating Due Experiments")
            startup_judge = StartupJudgeAgent(llm, config, scaffolder)

            for pending in due:
                console.print(f"  Evaluating: [cyan]{pending.slug}[/]")

                if dry_run:
                    console.print("    [dim](dry run — skipping)[/]")
                    continue

                with console.status("  Running Mode C evaluation..."):
                    result = startup_judge.evaluate_experiment(pending)

                _print_experiment_result(result)

                if result.recommendation == "promote":
                    try:
                        new_path = scaffolder.promote_experiment(pending.slug)
                        console.print(
                            f"    [green]Promoted to:[/] {new_path}"
                        )
                    except FileNotFoundError:
                        console.print("    [red]Experiment folder not found[/]")
                    vault.write_experiment_result(
                        result.model_dump(), run_id
                    )
                elif result.recommendation == "scrap":
                    vault.write_rejection(
                        {
                            "name": pending.idea_name,
                            "reasoning": result.evidence,
                            "weighted_score": result.score,
                        },
                        "experiment",
                        run_id,
                    )
                # "iterate" — re-queue handled by caller if needed

                state_mgr.remove_pending_experiment(pending.slug)

        if eval_experiments_only:
            state_mgr.save()
            console.rule("[bold green]Done (experiments only)")
            return

    # ── Step 2: Scan vault context ───────────────────────────
    console.rule("[bold]Scanning Vault")

    max_notes = config["engine"]["max_vault_context_notes"]
    strategy = config["engine"]["context_selection"]
    quarantined_paths = state_mgr.get_quarantined_paths()

    with console.status("Scanning vault notes..."):
        vault_notes = vault.select_context_notes(
            max_notes, strategy, exclude_paths=quarantined_paths
        )

    console.print(f"  Selected [cyan]{len(vault_notes)}[/] context notes")
    if quarantined_paths:
        console.print(
            f"  Quarantined notes excluded: [yellow]{len(quarantined_paths)}[/]"
        )

    # ── Step 2b: Entropy injection ──────────────────────────
    entropy_concept = None
    if config.get("entropy", {}).get("enabled", True):
        with console.status("Fetching entropy concept..."):
            entropy_concept = fetch_entropy_concept(
                config,
                vault_notes=vault_notes,
                run_count=state_mgr.state.run_count,
            )
        if entropy_concept:
            console.print(
                f"  Entropy: [magenta]{entropy_concept.title}[/] "
                f"({entropy_concept.strategy}, {entropy_concept.domain})"
            )
        else:
            console.print("  Entropy: [dim]none (fetch failed or disabled)[/]")

    # ── Step 2c: Novelty decay ───────────────────────────────
    overused = state_mgr.get_overused_concepts(novelty_threshold)
    overused_list = sorted(overused.keys()) if overused else []
    if overused_list:
        console.print(
            f"  Overused concepts: [yellow]{len(overused_list)}[/] "
            f"({', '.join(overused_list[:5])}{'...' if len(overused_list) > 5 else ''})"
        )

    # ── Step 3: Generate ideas ───────────────────────────────
    console.rule("[bold]Generating Ideas")
    generator = GeneratorAgent(llm, config)
    n_ideas = config["engine"]["ideas_per_run"]

    with console.status(f"Generating {n_ideas} ideas per category..."):
        output = generator.generate(
            vault_notes,
            state_mgr.state.seen_idea_titles,
            n_ideas,
            entropy_concept=entropy_concept,
            overused_concepts=overused_list if overused_list else None,
        )

    ideas_generated = len(output.essay_ideas) + len(output.startup_ideas)

    # Track ALL generated titles (even those that will be rejected)
    all_titles = [idea.title for idea in output.essay_ideas] + [
        idea.name for idea in output.startup_ideas
    ]
    state_mgr.add_seen_titles(all_titles)

    # Record concepts for novelty decay tracking
    for idea in output.essay_ideas:
        state_mgr.record_concepts(f"{idea.title} {idea.hook} {idea.argument_sketch}")
    for idea in output.startup_ideas:
        state_mgr.record_concepts(f"{idea.name} {idea.problem} {idea.insight}")

    console.print(
        f"  Generated [cyan]{len(output.essay_ideas)}[/] essay ideas, "
        f"[cyan]{len(output.startup_ideas)}[/] startup ideas"
    )

    if generate_only:
        _print_generated_ideas(output)
        state_mgr.state.vault_hash = vault.compute_content_hash()
        state_mgr.add_run_record(
            RunRecord(
                run_id=run_id,
                timestamp=datetime.now(),
                ideas_generated=ideas_generated,
                vault_hash=state_mgr.state.vault_hash,
            )
        )
        if not dry_run:
            state_mgr.save()
        console.rule("[bold green]Done (generate only)")
        return

    # ── Step 4: Judge essay ideas ────────────────────────────
    console.rule("[bold]Judging Essay Ideas")
    essay_judge = EssayJudgeAgent(llm, config)

    essay_table = Table(title="Essay Judgments")
    essay_table.add_column("Title", style="cyan", max_width=40)
    essay_table.add_column("Score", justify="right")
    essay_table.add_column("Verdict")
    essay_table.add_column("Reasoning", max_width=50)

    for idea in output.essay_ideas:
        idea_dict = idea.model_dump()

        with console.status(f"  Judging: {idea.title[:40]}..."):
            judgment = essay_judge.judge(
                idea_dict, vault_notes, overused_concepts=overused or None
            )

        verdict_style = "green" if judgment.verdict == "keep" else "red"
        essay_table.add_row(
            judgment.idea_title,
            f"{judgment.weighted_score:.2f}",
            f"[{verdict_style}]{judgment.verdict}[/{verdict_style}]",
            judgment.reasoning[:50] + "..." if len(judgment.reasoning) > 50 else judgment.reasoning,
        )

        if not dry_run:
            if judgment.verdict == "keep":
                path = vault.write_essay_idea(
                    idea_dict, judgment.model_dump(), run_id
                )
                state_mgr.quarantine_note(str(path), quarantine_cycles)
                console.print(
                    Panel(
                        f"[green bold]{idea.title}[/]\n"
                        f"Score: {judgment.weighted_score:.2f}\n"
                        f"Written to: {path}",
                        title="Approved Essay",
                    )
                )
                essays_approved += 1
            else:
                vault.write_rejection(
                    {
                        "title": idea.title,
                        "reasoning": judgment.reasoning,
                        "weighted_score": judgment.weighted_score,
                        "improvement_note": judgment.improvement_note,
                    },
                    "essay",
                    run_id,
                )
                essays_rejected += 1
        else:
            if judgment.verdict == "keep":
                essays_approved += 1
            else:
                essays_rejected += 1

    console.print(essay_table)

    # ── Step 5: Judge startup ideas ──────────────────────────
    console.rule("[bold]Judging Startup Ideas")
    startup_judge = StartupJudgeAgent(llm, config, scaffolder)

    startup_table = Table(title="Startup Judgments")
    startup_table.add_column("Name", style="cyan", max_width=40)
    startup_table.add_column("Score", justify="right")
    startup_table.add_column("Verdict")
    startup_table.add_column("Type", style="dim")
    startup_table.add_column("Reasoning", max_width=50)

    startup_rows: list[tuple] = []

    for idea in output.startup_ideas:
        idea_dict = idea.model_dump()

        with console.status(f"  Judging: {idea.name[:40]}..."):
            judgment = startup_judge.judge_viability(
                idea_dict, overused_concepts=overused or None
            )

        verdict_style = "green" if judgment.verdict == "viable" else "red"
        exp_type = ""

        if judgment.verdict == "viable":
            startups_approved += 1
            if not dry_run:
                startup_path = vault.write_startup_judgment(
                    idea_dict, judgment.model_dump(), run_id
                )
                state_mgr.quarantine_note(str(startup_path), quarantine_cycles)

                with console.status(f"  Scaffolding experiment: {idea.name}..."):
                    pending = startup_judge.scaffold_experiment(idea_dict)

                exp_type = pending.experiment_type
                state_mgr.add_pending_experiment(pending)
                console.print(
                    Panel(
                        f"[green bold]{idea.name}[/]\n"
                        f"Score: {judgment.weighted_score:.2f}\n"
                        f"Type: {pending.experiment_type}\n"
                        f"Experiment: {pending.experiment_path}\n"
                        f"Eval after: {pending.eval_after}",
                        title="Viable Startup — Experiment Scaffolded",
                    )
                )
        else:
            startups_rejected += 1
            if not dry_run:
                vault.write_rejection(
                    {
                        "name": idea.name,
                        "reasoning": judgment.reasoning,
                        "weighted_score": judgment.weighted_score,
                    },
                    "startup",
                    run_id,
                )

        startup_table.add_row(
            judgment.idea_name,
            f"{judgment.weighted_score:.2f}",
            f"[{verdict_style}]{judgment.verdict}[/{verdict_style}]",
            exp_type or "-",
            judgment.reasoning[:50] + "..." if len(judgment.reasoning) > 50 else judgment.reasoning,
        )

    console.print(startup_table)

    # ── Step 6: Save state ───────────────────────────────────
    state_mgr.state.vault_hash = vault.compute_content_hash()
    state_mgr.add_run_record(
        RunRecord(
            run_id=run_id,
            timestamp=datetime.now(),
            ideas_generated=ideas_generated,
            essays_approved=essays_approved,
            essays_rejected=essays_rejected,
            startups_approved=startups_approved,
            startups_rejected=startups_rejected,
            vault_hash=state_mgr.state.vault_hash,
        )
    )

    if not dry_run:
        state_mgr.save()

    console.rule("[bold green]Run Complete")
    console.print(
        f"  Run #{state_mgr.state.run_count} | "
        f"Essays: [green]{essays_approved} approved[/], "
        f"[red]{essays_rejected} rejected[/]\n"
        f"  Startups: [green]{startups_approved} viable[/], "
        f"[red]{startups_rejected} rejected[/]\n"
        f"  Pending experiments: "
        f"[cyan]{len(state_mgr.state.pending_experiments)}[/] | "
        f"Quarantined notes: "
        f"[yellow]{len(state_mgr.state.quarantined_notes)}[/]"
    )


# ── Display Helpers ──────────────────────────────────────────────


def _print_generated_ideas(output):
    """Print generated ideas for --generate-only mode."""
    if output.essay_ideas:
        console.print("\n[bold]Essay Ideas:[/]")
        for idea in output.essay_ideas:
            console.print(
                Panel(
                    f"[bold]{idea.title}[/]\n\n"
                    f"[italic]{idea.hook}[/]\n\n"
                    f"{idea.argument_sketch}\n\n"
                    f"Novelty: {idea.novelty_claim}\n"
                    f"Connections: {', '.join(idea.connections)}",
                )
            )

    if output.startup_ideas:
        console.print("\n[bold]Startup Ideas:[/]")
        for idea in output.startup_ideas:
            console.print(
                Panel(
                    f"[bold]{idea.name}[/]\n\n"
                    f"Problem: {idea.problem}\n"
                    f"Insight: {idea.insight}\n"
                    f"Target: {idea.target_user}\n"
                    f"Mechanic: {idea.core_mechanic}\n"
                    f"Hypothesis: {idea.experiment_hypothesis}\n"
                    f"Kill criteria: {idea.falsification_criteria}",
                )
            )


def _print_experiment_result(result):
    """Print experiment evaluation result."""
    verdict_color = {
        "validated": "green",
        "falsified": "red",
        "inconclusive": "yellow",
    }.get(result.hypothesis_verdict, "white")

    rec_color = {
        "promote": "green",
        "scrap": "red",
        "iterate": "yellow",
    }.get(result.recommendation, "white")

    console.print(
        f"    Verdict: [{verdict_color}]{result.hypothesis_verdict}[/{verdict_color}] "
        f"| Score: {result.score:.1f} "
        f"| Recommendation: [{rec_color}]{result.recommendation}[/{rec_color}]"
    )
    if result.evidence:
        console.print(f"    Evidence: {result.evidence[:100]}")


# ── CLI ──────────────────────────────────────────────────────────


@click.command()
@click.option("--daemon", is_flag=True, help="Run indefinitely on schedule")
@click.option(
    "--eval-experiments",
    "eval_experiments",
    is_flag=True,
    help="Only evaluate pending experiments",
)
@click.option(
    "--generate-only",
    "generate_only",
    is_flag=True,
    help="Only generate ideas, skip judging",
)
@click.option("--dry-run", is_flag=True, help="Print what would happen, write nothing")
@click.option("--config", "config_path", default="config.yaml", help="Config file path")
def main(daemon, eval_experiments, generate_only, dry_run, config_path):
    """Obsidian Idea Engine — generate, judge, and scaffold ideas."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config(config_path)
    validate_config(config)

    if dry_run:
        console.print("[yellow bold]DRY RUN — no files will be written[/]\n")

    if daemon:
        interval = config["engine"]["run_interval_minutes"]
        console.print(
            f"[bold]Daemon mode:[/] running every {interval} minutes\n"
        )

        # Run immediately
        run_once(config, dry_run=dry_run)

        schedule.every(interval).minutes.do(
            run_once, config=config, dry_run=dry_run
        )

        try:
            while True:
                schedule.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down...[/]")
    else:
        run_once(
            config,
            dry_run=dry_run,
            generate_only=generate_only,
            eval_experiments_only=eval_experiments,
        )


if __name__ == "__main__":
    main()
