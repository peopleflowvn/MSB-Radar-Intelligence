from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def _read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def build_runtime_values(
    source: dict[str, str], current: dict[str, str], *, embedding_model: str = "",
) -> dict[str, str]:
    token = current.get("RADAR_SERVICE_TOKEN") or secrets.token_urlsafe(48)
    index_token = current.get("RADAR_INDEX_SCOPE_TOKEN") or secrets.token_urlsafe(48)
    general_model = source.get("MSB_AI_GREENNODE_MODEL", "")
    return {
        "RADAR_BASE_URL": current.get("RADAR_BASE_URL") or "https://dev-radar.tunghr.io.vn",
        "RADAR_SERVICE_TOKEN": token,
        "RADAR_INDEX_SCOPE_TOKEN": index_token,
        "GREENNODE_BASE_URL": source.get("MSB_AI_GREENNODE_BASE_URL", ""),
        "GREENNODE_API_KEY": source.get("MSB_AI_GREENNODE_API_KEY", ""),
        "GREENNODE_MODEL_FAST": current.get("GREENNODE_MODEL_FAST") or general_model,
        "GREENNODE_MODEL_DEEP": current.get("GREENNODE_MODEL_DEEP") or general_model,
        "GREENNODE_MODEL_VISION": current.get("GREENNODE_MODEL_VISION") or general_model,
        # Never put a chat model into the embedding slot. Provision this only
        # after the production route has been inspected and live-tested.
        "GREENNODE_MODEL_EMBEDDING": embedding_model or current.get("GREENNODE_MODEL_EMBEDDING", ""),
        "HAYSTACK_TELEMETRY_ENABLED": "false",
    }


def write_runtime_env(source_path: Path, target_path: Path, *, embedding_model: str = "") -> None:
    values = build_runtime_values(
        _read(source_path), _read(target_path), embedding_model=embedding_model,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        "".join(f"{name}={value}\n" for name, value in values.items()),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--embedding-model", default="")
    args = parser.parse_args()
    write_runtime_env(args.source, args.target, embedding_model=args.embedding_model)


if __name__ == "__main__":
    main()
