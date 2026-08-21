from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from talk2data.domain.models import InterpretationProposal, TenantDomainPack
from talk2data.services.interpreter import InterpretationError, OllamaQuestionInterpreter

TextGenerator = Callable[[list[dict[str, str]]], str]


@dataclass(frozen=True)
class TransformersConfiguration:
    """Configuration for a small local Transformers question interpreter."""

    model_id: str = "Qwen/Qwen2.5-0.5B-Instruct"
    max_new_tokens: int = 192
    device: str = "auto"
    cache_dir: Path | None = None
    local_files_only: bool = False
    trust_remote_code: bool = False

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id cannot be blank")
        if not 16 <= self.max_new_tokens <= 512:
            raise ValueError("max_new_tokens must be between 16 and 512")
        if self.device not in {"auto", "cpu", "cuda", "mps"}:
            raise ValueError("device must be one of auto, cpu, cuda, or mps")


class TransformersQuestionInterpreter:
    """Runs a small open model locally and returns an untrusted structured proposal.

    The adapter intentionally exposes the same ``interpret`` method used by the Ollama
    provider. Talk2Data still validates every proposed business identifier against the
    governed Tenant Domain Pack before the proposal can affect a query plan.
    """

    def __init__(
        self,
        configuration: TransformersConfiguration,
        *,
        text_generator: TextGenerator | None = None,
    ) -> None:
        self._configuration = configuration
        self._text_generator = text_generator
        self._load_lock = threading.Lock()
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._resolved_device: str | None = None

    @property
    def model_id(self) -> str:
        return self._configuration.model_id

    async def interpret(self, question: str, pack: TenantDomainPack) -> InterpretationProposal:
        messages = self._build_messages(question, pack)
        try:
            if self._text_generator is not None:
                generated = self._text_generator(messages)
            else:
                generated = await asyncio.to_thread(self._generate_text, messages)
            payload = extract_first_json_object(generated)
            return InterpretationProposal.model_validate(payload)
        except InterpretationError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InterpretationError(
                "The local Transformers model returned an invalid structured interpretation"
            ) from exc

    async def preload(self) -> None:
        """Load the model before the first request when a host prefers eager startup."""

        if self._text_generator is None:
            await asyncio.to_thread(self._ensure_loaded)

    async def health(self) -> tuple[bool, str]:
        if self._text_generator is not None:
            return True, "Injected Transformers test generator is ready."
        if importlib.util.find_spec("transformers") is None:
            return False, "The transformers package is not installed."
        if importlib.util.find_spec("torch") is None:
            return False, "The torch package is not installed."
        if self._model is None:
            return True, f"Model {self.model_id!r} is configured and will load on first use."
        return True, f"Model {self.model_id!r} is loaded on {self._resolved_device}."

    def _build_messages(
        self,
        question: str,
        pack: TenantDomainPack,
    ) -> list[dict[str, str]]:
        prompt = OllamaQuestionInterpreter._build_prompt(question, pack)
        return [
            {
                "role": "system",
                "content": (
                    "You are a business-question parser. Do not answer the question. "
                    "Return one JSON object and no markdown. Match the supplied JSON schema. "
                    "Use only exact governed IDs supplied in the tenant catalog. Never invent "
                    "a metric, entity, dimension, or domain ID. Use empty lists when no governed "
                    "identifier applies."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _generate_text(self, messages: list[dict[str, str]]) -> str:
        self._ensure_loaded()
        if self._tokenizer is None or self._model is None or self._torch is None:
            raise InterpretationError("The local Transformers model did not initialize")

        tokenizer = self._tokenizer
        model = self._model
        torch = self._torch
        try:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

        inputs = tokenizer(prompt, return_tensors="pt")
        resolved_device = self._resolved_device or "cpu"
        if hasattr(inputs, "to"):
            inputs = inputs.to(resolved_device)
        else:
            inputs = {
                key: value.to(resolved_device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
        input_length = int(inputs["input_ids"].shape[-1])
        pad_token_id = tokenizer.pad_token_id
        if pad_token_id is None:
            pad_token_id = tokenizer.eos_token_id

        try:
            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=self._configuration.max_new_tokens,
                    do_sample=False,
                    use_cache=True,
                    pad_token_id=pad_token_id,
                )
        except Exception as exc:  # provider boundary: normalize framework failures
            raise InterpretationError(f"Transformers generation failed: {exc}") from exc

        generated_tokens = generated[0][input_length:]
        return str(tokenizer.decode(generated_tokens, skip_special_tokens=True)).strip()

    def _ensure_loaded(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        with self._load_lock:
            if self._model is not None and self._tokenizer is not None:
                return
            try:
                transformers = importlib.import_module("transformers")
                torch = importlib.import_module("torch")
            except ImportError as exc:
                raise InterpretationError(
                    "Transformers hosting requires the torch and transformers packages"
                ) from exc

            device = resolve_device(torch, self._configuration.device)
            model_kwargs: dict[str, Any] = {
                "local_files_only": self._configuration.local_files_only,
                "trust_remote_code": self._configuration.trust_remote_code,
                "low_cpu_mem_usage": True,
            }
            if self._configuration.cache_dir is not None:
                model_kwargs["cache_dir"] = str(self._configuration.cache_dir)
            if device == "cpu":
                model_kwargs["torch_dtype"] = torch.float32
            else:
                model_kwargs["torch_dtype"] = "auto"

            try:
                tokenizer = transformers.AutoTokenizer.from_pretrained(
                    self._configuration.model_id,
                    local_files_only=self._configuration.local_files_only,
                    trust_remote_code=self._configuration.trust_remote_code,
                    cache_dir=(
                        None if self._configuration.cache_dir is None else str(self._configuration.cache_dir)
                    ),
                )
                model = transformers.AutoModelForCausalLM.from_pretrained(
                    self._configuration.model_id,
                    **model_kwargs,
                )
                model.to(device)
                model.eval()
            except Exception as exc:  # provider boundary: normalize framework failures
                raise InterpretationError(
                    f"Unable to load local model {self._configuration.model_id!r}: {exc}"
                ) from exc

            self._tokenizer = tokenizer
            self._model = model
            self._torch = torch
            self._resolved_device = device


def resolve_device(torch_module: Any, requested: str) -> str:
    if requested != "auto":
        if requested == "cuda" and not bool(torch_module.cuda.is_available()):
            raise InterpretationError("CUDA was requested but is not available")
        if requested == "mps":
            mps = getattr(getattr(torch_module, "backends", object()), "mps", None)
            if mps is None or not bool(mps.is_available()):
                raise InterpretationError("MPS was requested but is not available")
        return requested
    if bool(torch_module.cuda.is_available()):
        return "cuda"
    mps = getattr(getattr(torch_module, "backends", object()), "mps", None)
    if mps is not None and bool(mps.is_available()):
        return "mps"
    return "cpu"


def extract_first_json_object(value: str) -> dict[str, Any]:
    """Return the first complete JSON object from model output.

    Small local models occasionally wrap valid JSON in prose or a fenced code block.
    Talk2Data accepts the object only after strict Pydantic validation; all surrounding
    text is ignored rather than treated as evidence.
    """

    decoder = json.JSONDecoder()
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    raise InterpretationError("No complete JSON object was found in model output")
