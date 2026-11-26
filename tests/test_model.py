from __future__ import annotations

import json

import httpx
import pytest

from manifestfix.lenient_json import parse_lenient
from manifestfix.model import FakeExtractor, ModelConfigError, OpenAICompatModel, prompt_pairs


def test_clean_extraction_is_correct(dataset):
    fake = FakeExtractor({})
    doc = dataset.docs[5]
    assert json.loads(fake.extract(doc.text))["bl_number"] == doc.manifest["bl_number"]


def test_prompt_pairs_parse_code_and_path():
    prompt = (
        "x\n- ISO6346_CHECK_DIGIT at containers[1].container_no: bad\n- SUM_GROSS at containers: no"
    )
    assert prompt_pairs(prompt) == {
        ("ISO6346_CHECK_DIGIT", "containers[1].container_no"),
        ("SUM_GROSS", "containers"),
    }
    assert prompt_pairs("The output was invalid. Try again.") == set()


def test_fake_needs_both_code_and_path(dataset):
    doc = next(
        d
        for d in dataset.docs
        if dataset.plan.get(d.doc_id)
        and dataset.plan[d.doc_id].type == "digit_transposition"
        and not dataset.plan[d.doc_id].stubborn
    )
    fault = dataset.plan[doc.doc_id]
    fake = FakeExtractor(dataset.plan)
    right = f"- {fault.code} at {fault.path}: x"
    assert json.loads(fake.repair(doc.text, "{}", right))["patch"]
    wrong_path = f"- {fault.code} at containers[9].container_no: x"
    assert json.loads(fake.repair(doc.text, "{}", wrong_path))["patch"] == []
    wrong_code = f"- SUM_GROSS at {fault.path}: x"
    assert json.loads(fake.repair(doc.text, "{}", wrong_code))["patch"] == []


def test_stubborn_faults_are_never_fixed(dataset):
    doc = next(
        d for d in dataset.docs if dataset.plan.get(d.doc_id) and dataset.plan[d.doc_id].stubborn
    )
    fault = dataset.plan[doc.doc_id]
    fake = FakeExtractor(dataset.plan)
    prompt = f"- {fault.code} at {fault.path}: x"
    assert json.loads(fake.repair(doc.text, "{}", prompt))["patch"] == []


def test_blind_retry_repeats_the_same_faulty_output(dataset):
    doc = next(
        d
        for d in dataset.docs
        if dataset.plan.get(d.doc_id) and dataset.plan[d.doc_id].type == "dropped_line"
    )
    fake = FakeExtractor(dataset.plan)
    assert fake.repair(doc.text, "{}", "try again") == fake.extract(doc.text)


def test_formatting_faults_are_applied_to_the_text_and_survive_lenient_parsing(dataset):
    fake = FakeExtractor(dataset.plan)
    for kind in ("markdown_fence", "trailing_comma"):
        doc = next(
            d
            for d in dataset.docs
            if dataset.plan.get(d.doc_id) and dataset.plan[d.doc_id].type == kind
        )
        text = fake.extract(doc.text)
        with pytest.raises(json.JSONDecodeError):
            json.loads(text)
        assert parse_lenient(text).data == parse_lenient(FakeExtractor({}).extract(doc.text)).data


def _mock_transport(captured: list[httpx.Request], content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


def test_openai_compat_model_sends_json_mode_request():
    captured: list[httpx.Request] = []
    model = OpenAICompatModel(
        base_url="http://llm.test/v1/",
        api_key="k",
        model="m1",
        transport=_mock_transport(captured, '{"ok": true}'),
    )
    assert model.extract("some document") == '{"ok": true}'
    request = captured[0]
    body = json.loads(request.content)
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer k"
    assert body["model"] == "m1"
    assert body["response_format"] == {"type": "json_object"}
    assert "some document" in body["messages"][1]["content"]


def test_openai_repair_shows_document_only_for_blind_retries():
    captured: list[httpx.Request] = []
    model = OpenAICompatModel("http://llm.test", "", "m", transport=_mock_transport(captured, "{}"))
    model.repair("DOC BODY", "{}", "- SUM_GROSS at containers: bad")
    model.repair("DOC BODY", "{}", "The output was invalid. Try again.")
    targeted, blind = (json.loads(r.content)["messages"][1]["content"] for r in captured)
    assert "DOC BODY" not in targeted
    assert "DOC BODY" in blind
    assert "authorization" not in captured[0].headers


def test_openai_config_comes_from_environment(monkeypatch):
    monkeypatch.delenv("MANIFESTFIX_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("MANIFESTFIX_LLM_MODEL", raising=False)
    with pytest.raises(ModelConfigError):
        OpenAICompatModel()
    monkeypatch.setenv("MANIFESTFIX_LLM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("MANIFESTFIX_LLM_MODEL", "m")
    model = OpenAICompatModel()
    assert (model.base_url, model.model) == ("http://x/v1", "m")
