from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("VERIFY")


@dataclass(frozen=True)
class VoiceConfig:
    id: str
    name: str


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    voice: VoiceConfig
    language_code: str | None
    output_format: str
    max_chars: int | None
    usd_per_1m_chars: float | None
    voice_settings: dict[str, Any] | None = None
    location: str | None = None  # cloud region/endpoint for providers that need one (Gemini: "global")
    mode: str = "batch"  # "batch" | "stream"
    # Gemini only, `--variant emotive`: the tag values sent as speech_metadata.style (see runner/emotion.py).
    emotive_styles: tuple[str, ...] = ()

    def estimate_cost(self, billed_chars: int) -> float | None:
        if self.usd_per_1m_chars is None:
            return None
        return billed_chars * self.usd_per_1m_chars / 1_000_000


def load_provider_config(path: str | Path, provider: str, mode: str = "batch") -> ProviderConfig:
    """An optional `batch:` / `stream:` block under the provider overrides keys for that mode."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        raw = data["providers"][provider]
    except KeyError:
        raise ConfigError(f"provider {provider!r} not found in {path}") from None
    raw = {**raw, **(raw.get(mode) or {})}

    voice = raw.get("voice") or {}
    required = {
        "model": raw.get("model"),
        "voice.id": voice.get("id"),
        "output_format": raw.get("output_format"),
    }
    bad = [k for k, v in required.items() if not v or _is_placeholder(v)]
    if bad:
        raise ConfigError(f"{provider}: set these in {path}: {bad}")

    price = raw.get("price") or {}
    usd = price.get("usd_per_unit")
    max_chars = raw.get("max_chars")
    return ProviderConfig(
        name=provider,
        model=str(raw["model"]),
        voice=VoiceConfig(id=str(voice["id"]), name=str(voice.get("name", voice["id"]))),
        language_code=raw.get("language_code"),
        output_format=str(raw["output_format"]),
        max_chars=max_chars if isinstance(max_chars, int) else None,
        usd_per_1m_chars=float(usd)
        if price.get("unit") == "per_1m_chars" and isinstance(usd, int | float)
        else None,
        voice_settings=raw.get("voice_settings"),
        location=raw.get("location"),
        mode=mode,
    )
