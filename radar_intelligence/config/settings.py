from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


REQUIRED_LIVE_SETTINGS = (
    "RADAR_BASE_URL",
    "RADAR_SERVICE_TOKEN",
    "RADAR_INDEX_SCOPE_TOKEN",
    "GREENNODE_BASE_URL",
    "GREENNODE_API_KEY",
    "GREENNODE_MODEL_FAST",
    "GREENNODE_MODEL_DEEP",
    "GREENNODE_MODEL_VISION",
    "GREENNODE_MODEL_EMBEDDING",
)


@dataclass(frozen=True)
class RuntimeSettings:
    values: Mapping[str, str]

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeSettings":
        source = os.environ if environ is None else environ
        values = {name: str(source.get(name, "")).strip() for name in REQUIRED_LIVE_SETTINGS}
        settings = cls(values)
        settings._validate()
        return settings

    def _validate(self) -> None:
        radar_url = self.values.get("RADAR_BASE_URL", "").rstrip("/").lower()
        if radar_url and not (
            radar_url.startswith("https://") or radar_url == "http://hub:8000"
        ):
            raise ValueError("RADAR_BASE_URL must use HTTPS or the fixed Docker-internal Hub URL")
        green_url = self.values.get("GREENNODE_BASE_URL", "")
        if green_url and not green_url.lower().startswith("https://"):
            raise ValueError("GREENNODE_BASE_URL must use HTTPS")

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in REQUIRED_LIVE_SETTINGS if not self.values.get(name))

    @property
    def ready(self) -> bool:
        return not self.missing

    def public_status(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "radar_configured": all(self.values.get(name) for name in (
                "RADAR_BASE_URL", "RADAR_SERVICE_TOKEN", "RADAR_INDEX_SCOPE_TOKEN",
            )),
            "greennode_configured": all(self.values.get(name) for name in (
                "GREENNODE_BASE_URL", "GREENNODE_API_KEY", "GREENNODE_MODEL_FAST",
                "GREENNODE_MODEL_DEEP", "GREENNODE_MODEL_VISION", "GREENNODE_MODEL_EMBEDDING",
            )),
        }
