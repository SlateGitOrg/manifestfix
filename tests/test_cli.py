from __future__ import annotations

from typer.testing import CliRunner

from manifestfix.cli import app
from manifestfix.generator import generate_dataset, write_dataset

runner = CliRunner()


def test_seed_writes_documents_truth_and_plan(tmp_path):
    result = runner.invoke(app, ["seed", "--out", str(tmp_path), "--count", "30", "--seed", "5"])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "docs").glob("*.txt"))) == 30
    assert (tmp_path / "truth.json").exists() and (tmp_path / "fault_plan.yaml").exists()


def test_extract_accepts_a_repaired_document_and_shows_the_trace(tmp_path):
    ds = generate_dataset(seed=7, count=300)
    write_dataset(ds, tmp_path)
    doc = next(
        d for d in ds.docs if ds.plan.get(d.doc_id) and ds.plan[d.doc_id].type == "dropped_line"
    )
    result = runner.invoke(
        app,
        [
            "extract",
            str(tmp_path / "docs" / f"{doc.doc_id}.txt"),
            "--fault-plan",
            str(tmp_path / "fault_plan.yaml"),
            "--trace",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accepted after 1 repair round" in result.output
    assert "SUM_PACKAGES at containers" in result.output
    assert doc.manifest["bl_number"] in result.output


def test_extract_sends_a_stubborn_document_to_review(tmp_path):
    ds = generate_dataset(seed=7, count=300)
    write_dataset(ds, tmp_path)
    doc = next(d for d in ds.docs if ds.plan.get(d.doc_id) and ds.plan[d.doc_id].stubborn)
    result = runner.invoke(
        app,
        [
            "extract",
            str(tmp_path / "docs" / f"{doc.doc_id}.txt"),
            "--fault-plan",
            str(tmp_path / "fault_plan.yaml"),
        ],
    )
    assert result.exit_code == 1
    assert "sent to review" in result.output and "ISO6346_CHECK_DIGIT" in result.output


def test_extract_without_a_plan_is_a_clean_extraction(tmp_path):
    ds = generate_dataset(seed=7, count=30)
    doc = ds.docs[0]
    path = tmp_path / "doc.txt"
    path.write_text(doc.text)
    result = runner.invoke(app, ["extract", str(path), "--fault-plan", str(tmp_path / "none.yaml")])
    assert result.exit_code == 0
    assert "accepted after 0 repair round" in result.output


def test_eval_without_a_dataset_explains_what_to_do(tmp_path):
    result = runner.invoke(app, ["eval", "--data", str(tmp_path / "missing")])
    assert result.exit_code != 0
    assert "seed" in result.output
