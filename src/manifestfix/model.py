"""Extraction models: a protocol, a deterministic offline model and an HTTP adapter."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

import httpx

from manifestfix import faults
from manifestfix.faults import Fault
from manifestfix.layouts import doc_id_of, parse_document
from manifestfix.schema import Manifest

SYSTEM_EXTRACT = (
    "You extract freight manifests from packing lists, emails and bills of lading. "
    "Reply with one JSON object that matches this JSON Schema exactly, with no extra fields. "
    "Weights are in kilograms: convert pounds (1 lb = 0.45359237 kg). Copy container numbers as "
    "printed; never invent or correct one. Port fields are UN/LOCODEs.\n\nSchema:\n{schema}"
)
SYSTEM_REPAIR = (
    "You repair a previous extraction of a freight document. Follow the instructions in the user "
    "message exactly and reply with one JSON object."
)
_PAIR = re.compile(r"^- (?P<code>[A-Z0-9_]+) at (?P<path>\S+?):", re.MULTILINE)


class ExtractionModel(Protocol):
    """What the pipeline needs from a model.

    `extract` returns the model's raw text. `repair` receives the document, the current JSON and
    the repair prompt (`errors`) and returns raw text: a patch for targeted prompts, a fresh full
    answer for a blind retry.
    """

    def extract(self, doc_text: str) -> str: ...

    def repair(self, doc_text: str, current_json: str, errors: str) -> str: ...


def prompt_pairs(prompt: str) -> set[tuple[str, str]]:
    """The (code, path) pairs a targeted repair prompt names."""
    return {(m["code"], m["path"]) for m in _PAIR.finditer(prompt)}


class FakeExtractor:
    """Offline model. It reads the synthetic document with the generator's layout parsers, so a
    clean extraction is correct, then applies the fault the plan assigns to the document id.

    On repair it fixes a fault only when the prompt names both the fault's code and its path, and
    never when the fault is marked stubborn. A prompt that names nothing specific is a blind
    retry, and the model answers it with the same faulty extraction again.
    """

    def __init__(self, plan: dict[str, Fault] | None = None) -> None:
        self.plan = plan or {}

    def _clean(self, doc_text: str) -> dict[str, Any]:
        return parse_document(doc_text)

    def _fault(self, doc_text: str) -> Fault | None:
        doc_id = doc_id_of(doc_text)
        return self.plan.get(doc_id) if doc_id else None

    def extract(self, doc_text: str) -> str:
        fault = self._fault(doc_text)
        clean = self._clean(doc_text)
        payload = faults.faulty_payload(fault, clean) if fault else clean
        return faults.render_output(fault, payload)

    def repair(self, doc_text: str, current_json: str, errors: str) -> str:
        pairs = prompt_pairs(errors)
        if not pairs:
            return self.extract(doc_text)
        fault = self._fault(doc_text)
        ops: list[dict[str, Any]] = []
        if fault and not fault.stubborn and faults.identify(fault) in pairs:
            ops = faults.fix_ops(fault, self._clean(doc_text))
        return json.dumps({"patch": ops})


class ModelConfigError(RuntimeError):
    pass


class OpenAICompatModel:
    """Chat-completions client for any OpenAI-compatible endpoint, using JSON mode.

    Configured by MANIFESTFIX_LLM_BASE_URL, MANIFESTFIX_LLM_API_KEY and MANIFESTFIX_LLM_MODEL.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("MANIFESTFIX_LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("MANIFESTFIX_LLM_API_KEY", "")
        self.model = model or os.environ.get("MANIFESTFIX_LLM_MODEL", "")
        if not self.base_url or not self.model:
            raise ModelConfigError(
                "set MANIFESTFIX_LLM_BASE_URL and MANIFESTFIX_LLM_MODEL "
                "(and MANIFESTFIX_LLM_API_KEY if the endpoint needs one)"
            )
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _chat(self, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        response = self._client.post(
            f"{self.base_url}/chat/completions", json=body, headers=headers
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def extract(self, doc_text: str) -> str:
        schema = json.dumps(Manifest.model_json_schema())
        return self._chat(SYSTEM_EXTRACT.format(schema=schema), f"Document:\n\n{doc_text}")

    def repair(self, doc_text: str, current_json: str, errors: str) -> str:
        user = f"Current extraction:\n{current_json}\n\n{errors}"
        if not prompt_pairs(errors):  # a blind retry has to see the document again
            user += f"\n\nDocument:\n\n{doc_text}"
        return self._chat(SYSTEM_REPAIR, user)
