"""Create or complete `.env` for the standalone stack (root docker-compose.yml).

Copies `.env.standalone.example` when `.env` is missing, then fills only the
secrets that are still empty. Existing values are never overwritten, so it is
safe to re-run on a host that already holds data.
"""
from __future__ import annotations

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = {
    "SECRET_KEY": lambda: secrets.token_urlsafe(50),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "INTELLIGENCE_SERVICE_TOKEN": lambda: secrets.token_urlsafe(48),
    "INTELLIGENCE_INDEX_SCOPE_TOKEN": lambda: secrets.token_urlsafe(48),
}


def fill_secrets(lines: list[str]) -> tuple[list[str], list[str]]:
    filled, seen, output = [], set(), []
    for line in lines:
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and not line.lstrip().startswith("#") and name in GENERATED:
            seen.add(name)
            if not value.strip():
                line = f"{name}={GENERATED[name]()}"
                filled.append(name)
        output.append(line)
    for name, make in GENERATED.items():
        if name not in seen:
            output.append(f"{name}={make()}")
            filled.append(name)
    return output, filled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--template", type=Path, default=ROOT / ".env.standalone.example")
    args = parser.parse_args()
    source = args.env if args.env.exists() else args.template
    lines, filled = fill_secrets(source.read_text(encoding="utf-8").splitlines())
    args.env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{args.env}: generated {', '.join(filled) if filled else 'nothing (all set)'}")


if __name__ == "__main__":
    main()
