from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SNAPSHOT_VERSION = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = (
    REPOSITORY_ROOT
    / "packages"
    / "python-cli"
    / "src"
    / "polygres_cli"
    / "openapi"
    / "control-plane-v1.json"
)


def build_snapshot() -> dict[str, Any]:
    _configure_deterministic_schema_environment()
    sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "polygres-lib" / "python" / "src"))
    sys.path.insert(0, str(REPOSITORY_ROOT / "services" / "api"))

    from app.main import create_app

    document = create_app().openapi()
    document["x-polygres-cli-snapshot-version"] = SNAPSHOT_VERSION
    _validate_snapshot(document)
    return document


def render_snapshot(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or validate the Polygres CLI OpenAPI snapshot."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the bundled snapshot differs from the FastAPI schema",
    )
    args = parser.parse_args(argv)

    rendered = render_snapshot(build_snapshot())
    if args.check:
        try:
            current = SNAPSHOT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"could not read {SNAPSHOT_PATH}: {exc}")
        if current != rendered:
            sys.stderr.write(
                f"{SNAPSHOT_PATH} is stale. Run "
                "packages/python-cli/tools/generate_openapi_snapshot.py.\n"
            )
            return 1
        sys.stdout.write(f"OpenAPI snapshot is current: {SNAPSHOT_PATH}\n")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(rendered, encoding="utf-8")
    sys.stdout.write(f"Wrote OpenAPI snapshot: {SNAPSHOT_PATH}\n")
    return 0


def _configure_deterministic_schema_environment() -> None:
    values = {
        "ENVIRONMENT": "local",
        "LOCAL_CONTROL_PLANE": "memory",
        "LOCAL_RUNTIME_MODE": "in_memory",
    }
    os.environ.update(values)


def _validate_snapshot(document: dict[str, Any]) -> None:
    if not isinstance(document.get("openapi"), str):
        raise ValueError("FastAPI did not produce an OpenAPI version.")
    paths = document.get("paths")
    if not isinstance(paths, dict) or "/v1/projects" not in paths:
        raise ValueError("FastAPI OpenAPI schema does not contain the control-plane routes.")
    operation_ids: set[str] = set()
    operation_count = 0
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            raise ValueError("FastAPI OpenAPI paths are malformed.")
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(operation, dict):
                raise ValueError(f"OpenAPI operation {method.upper()} {path} is malformed.")
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"OpenAPI operation {method.upper()} {path} has no operationId.")
            if operation_id in operation_ids:
                raise ValueError(f"OpenAPI operationId is not unique: {operation_id}")
            operation_ids.add(operation_id)
            operation_count += 1
    if operation_count == 0:
        raise ValueError("FastAPI OpenAPI schema contains no callable operations.")


if __name__ == "__main__":
    raise SystemExit(main())
