"""Command line interface: seed, extract, check-digit and eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from manifestfix import iso6346
from manifestfix.evaluate import FIELD_ORDER, ConfigResult, evaluate, predict
from manifestfix.faults import load_plan
from manifestfix.generator import (
    DEFAULT_COUNT,
    DEFAULT_SEED,
    generate_dataset,
    load_dataset,
    write_dataset,
)
from manifestfix.layouts import doc_id_of
from manifestfix.model import ExtractionModel, FakeExtractor, ModelConfigError, OpenAICompatModel
from manifestfix.repair import CONFIGS, Pipeline

app = typer.Typer(add_completion=False, help="Validate and repair LLM-extracted freight manifests.")
console = Console(width=110)


@app.command()
def seed(
    seed: Annotated[int, typer.Option(help="Random seed.")] = DEFAULT_SEED,
    count: Annotated[int, typer.Option(help="Number of documents.")] = DEFAULT_COUNT,
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("data"),
) -> None:
    """Generate synthetic documents, ground truth and the fault plan."""
    dataset = generate_dataset(seed, count)
    write_dataset(dataset, out)
    lines = sum(len(d.manifest["containers"]) for d in dataset.docs)
    console.print(
        f"wrote {len(dataset.docs)} documents ({lines} container lines) and "
        f"{len(dataset.plan)} planned faults to {out}/"
    )


@app.command("check-digit")
def check_digit(container_no: Annotated[str, typer.Argument(help="e.g. CSQU3054383")]) -> None:
    """Check an ISO 6346 container number."""
    try:
        result = iso6346.check(container_no)
    except ValueError as error:
        console.print(f"[red]error:[/red] {error}")
        raise typer.Exit(2) from error
    if result.valid:
        console.print(f"{result.container_no}: valid (check digit {result.computed})")
        return
    console.print(
        f"{result.container_no}: invalid (printed check digit {result.given}, "
        f"computed {result.computed})"
    )
    raise typer.Exit(1)


@app.command()
def extract(
    doc: Annotated[Path, typer.Argument(help="Document text file.")],
    config: Annotated[str, typer.Option(help="schema-only, rules+blind or rules+targeted.")] = (
        "rules+targeted"
    ),
    fault_plan: Annotated[Path, typer.Option(help="Fault plan for the offline model.")] = Path(
        "data/fault_plan.yaml"
    ),
    model: Annotated[str, typer.Option(help="fake (offline) or openai (env-configured).")] = "fake",
    trace: Annotated[bool, typer.Option(help="Print the repair trace.")] = False,
) -> None:
    """Extract one document and print the accepted JSON or the review reasons."""
    if config not in CONFIGS:
        raise typer.BadParameter(f"config must be one of {', '.join(CONFIGS)}")
    text = doc.read_text()
    llm: ExtractionModel
    if model == "fake":
        llm = FakeExtractor(load_plan(fault_plan) if fault_plan.exists() else {})
    elif model == "openai":
        try:
            llm = OpenAICompatModel()
        except ModelConfigError as error:
            raise typer.BadParameter(str(error)) from error
    else:
        raise typer.BadParameter("model must be fake or openai")
    outcome = Pipeline(llm, CONFIGS[config]).run(text)
    label = doc_id_of(text) or doc.name
    if trace:
        console.print(f"[bold]{label}[/bold] trace ({config})")
        for step in outcome.trace:
            console.print(f"  {step}", markup=False)
        for n, prompt in enumerate(outcome.prompts, start=1):
            console.print(f"\nrepair prompt {n}:\n{prompt}", markup=False, soft_wrap=True)
            console.print(
                f"\nmodel response {n}:\n{outcome.patches[n - 1]}", markup=False, soft_wrap=True
            )
        console.print()
    if outcome.status == "accepted":
        console.print(
            f"{label}: accepted after {outcome.rounds} repair round(s), {outcome.calls} call(s)"
        )
        console.print_json(json.dumps(outcome.manifest))
        return
    console.print(f"{label}: sent to review after {outcome.rounds} repair round(s)")
    for reason in outcome.reasons:
        console.print(f"  {reason.code} at {reason.path}: {reason.message}", markup=False)
    raise typer.Exit(1)


def _outcome_table(results: list[ConfigResult], total: int) -> Table:
    table = Table(title=f"Outcomes over {total} documents")
    for column in (
        "Config",
        "Accepted-correct",
        "Silent errors",
        "Review",
        "Calls per accepted doc",
    ):
        table.add_column(column, justify="left" if column == "Config" else "right")
    for r in results:
        table.add_row(
            r.name,
            str(r.accepted_correct),
            str(r.silent_errors),
            str(r.review),
            f"{r.calls_per_accepted:.3f} ({r.calls}/{r.accepted})",
        )
    return table


def _field_table(results: list[ConfigResult]) -> Table:
    table = Table(title="Per-field exact accuracy (accepted documents only)")
    table.add_column("Field")
    for r in results:
        table.add_column(r.name, justify="right")
    for name in FIELD_ORDER:
        table.add_row(name, *(f"{r.field_accuracy(name) * 100:.1f}%" for r in results))
    return table


@app.command("eval")
def eval_command(
    configs: Annotated[str, typer.Option(help="'all' or a comma-separated list.")] = "all",
    data: Annotated[Path, typer.Option(help="Directory written by `seed`.")] = Path("data"),
    json_out: Annotated[Path | None, typer.Option(help="Write results as JSON.")] = None,
) -> None:
    """Score configurations against ground truth."""
    names = list(CONFIGS) if configs == "all" else [c.strip() for c in configs.split(",")]
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise typer.BadParameter(f"unknown config(s): {', '.join(unknown)}")
    if not (data / "truth.json").exists():
        raise typer.BadParameter(f"no dataset in {data}/; run `manifestfix seed` first")
    dataset = load_dataset(data)
    results = evaluate(names, dataset)
    total = len(dataset.docs)
    console.print(_outcome_table(results, total))
    console.print(_field_table(results))
    console.print("Expected from the fault plan alone:")
    for r in results:
        e = predict(dataset.plan, total, r.name)
        console.print(
            f"  {r.name}: {e.accepted_correct} correct, {e.silent_errors} silent, "
            f"{e.review} review, {e.calls} calls",
            markup=False,
        )
    if json_out:
        payload = {
            r.name: {
                "accepted_correct": r.accepted_correct,
                "silent_errors": r.silent_errors,
                "review": r.review,
                "calls": r.calls,
                "calls_per_accepted": round(r.calls_per_accepted, 3),
                "field_accuracy": {f: round(r.field_accuracy(f), 4) for f in FIELD_ORDER},
            }
            for r in results
        }
        json_out.write_text(json.dumps(payload, indent=2))
