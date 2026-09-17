"""Opt-in embedding summaries, bounded observation and version-fenced recovery."""

import json
import sys
import time

import httpx
from pydantic import ValidationError

from polygres_cli._vendor.polygres_lib.embeddings.models import EmbeddingChunkingRecovery
from polygres_cli.cli_errors import CONFLICT, UNAVAILABLE, USAGE, CliError
from polygres_cli.cli_output import write_json


def request(ctx, *args, **kwargs):
    """Explain only precise new-field rejections, preserving every other server error."""
    try:
        return ctx.client._runtime.request(*args, **kwargs)
    except CliError as exc:
        body = kwargs.get("json") or {}
        automatic = body.get("chunking", {}).get("mode") == "automatic"
        recovery = body.get("action") in {"preview_chunking", "enable_chunking"}
        errors = exc.details.get("errors", [])
        if not isinstance(errors, list):
            errors = []
        unsupported = any(
            isinstance(error, dict)
            and (
                automatic
                and error.get("loc") == ["body", "chunking", "mode"]
                and error.get("type") == "extra_forbidden"
                or recovery
                and error.get("loc") == ["body", "action"]
                and error.get("type") == "literal_error"
            )
            for error in errors
        )
        if exc.status_code == 422 and exc.code == "VALIDATION_ERROR" and unsupported:
            raise CliError(
                "EMBEDDING_FEATURE_UNSUPPORTED",
                "This server needs an upgrade for automatic chunking and oversized recovery. "
                "No fallback or ordinary retry was attempted.",
                exit_code=USAGE,
                request_id=exc.request_id,
            ) from None
        raise


def render_summary(value, *, action="get", chunking=None):
    if isinstance(value, list):
        return "\n\n".join(render_summary(row) for row in value) or "No configurations."
    if "configurations" in value:
        return render_summary(value["configurations"])
    if action == "preview":
        mode = (chunking or {}).get("mode") or (
            "custom" if (chunking or {}).get("enabled") else "off"
        )
        return (
            f"Source documents: {value.get('source_rows', 'not reported')}\n"
            f"Sampled documents: {value.get('sampled_rows', 'not reported')}\n"
            f"Estimated input tokens: {value.get('estimated_input_tokens', 'not reported')}\n"
            "Estimated usage (microcredits): "
            f"{value.get('estimated_microcredits', 'not reported')}\n"
            f"Model input limit: {value.get('model', {}).get('max_input_tokens', 'not reported')} "
            "tokens\n"
            f"Chunking: {mode}; chunk examples returned: {len(value.get('sample_chunks', []))}\n"
            "Automatic splits only oversized documents; custom uses the configured chunk size.\n"
            "Preview is an estimate, not a guarantee that every source fits."
        )
    p = value.get("progress", {})
    lines = [
        f"{value.get('name', value.get('id', 'Configuration'))}: "
        f"{value.get('status', 'not reported')}"
    ]
    if action in {"create", "run", "pause", "resume", "retry", "reconcile"}:
        lines.append(f"{action.capitalize()} accepted; this does not mean processing is complete.")
    for label, key in (
        ("Currently embedded source documents", "embedded_rows"),
        ("Generated document versions", "generated"),
        ("Copied document versions", "copied"),
        ("Processing", "processing"),
        ("Pending", "pending"),
        ("Retrying", "retrying"),
        ("Recovering", "recovering"),
        ("Failed", "failed"),
        ("Uncertain", "uncertain"),
        ("Search updates pending", "context_pending"),
        ("Search updates failed", "context_failed"),
    ):
        lines.append(f"{label}: {p.get(key) if p.get(key) is not None else 'not reported'}")
    if p.get("next_retry_at"):
        lines.append(f"Next retry: {p['next_retry_at']}")
    chunking = value.get("settings", {}).get("chunking", {})
    if chunking:
        mode = chunking.get("mode") or ("custom" if chunking.get("enabled") else "off")
        lines.append(f"Chunking: {mode}")
        if mode == "automatic":
            lines.append(
                "Documents stay whole when they fit; oversized text splits at model limits."
            )
    if p.get("uncertain"):
        lines.append("Unknown provider outcomes need reconciliation; do not submit fresh calls.")
    if p.get("failed"):
        lines.append("For oversized failures, preview recovery with embeddings recover-oversized.")
    if p.get("context_pending") or p.get("context_failed"):
        lines.append("Search publication is not complete, even if generation has finished.")
    return "\n".join(lines)


def _preview_text(preview):
    lines = [
        f"{preview.eligible_rows} failed documents can be retried with automatic chunking.",
        f"{preview.blocked_rows} documents are not eligible for this recovery.",
        f"Model input limit: {preview.max_input_tokens} tokens.",
    ]
    for sample in preview.samples:
        lines.append(
            f"{json.dumps(sample.source_key, ensure_ascii=False)}: "
            f"{sample.input_tokens} input tokens -> {sample.chunks} chunks"
        )
    lines.extend(
        [
            "Eligible rows are rechecked when submitted; the final queued count may differ.",
            "Successful documents and unknown provider outcomes remain unchanged.",
            "Automatic chunking also applies to future source changes.",
            "A paused configuration remains paused.",
        ]
    )
    return "\n".join(lines)


def recover_oversized(ctx, args, project_id):
    try:
        return _recover_oversized(ctx, args, project_id)
    except KeyboardInterrupt:
        raise CliError(
            "EMBEDDING_RECOVERY_INTERRUPTED",
            "Recovery command interrupted. Inspect the configuration before retrying; "
            "any submitted request was not repeated.",
            exit_code=130,
        ) from None
    except (httpx.TimeoutException, httpx.NetworkError):
        raise CliError(
            "EMBEDDING_PREVIEW_UNAVAILABLE",
            "Could not fetch a recovery preview. No recovery change was submitted.",
            exit_code=UNAVAILABLE,
        ) from None


def _recover_oversized(ctx, args, project_id):
    path = f"/embeddings/configurations/{args.configuration_id}/actions"
    interactive = sys.stdin.isatty() and not ctx.json
    for attempt in range(3):
        raw = request(
            ctx,
            project_id,
            "context:manage",
            "POST",
            path,
            json={"action": "preview_chunking"},
            read_only_retry=True,
            timeout=130,
        )
        try:
            preview = EmbeddingChunkingRecovery.model_validate(raw)
        except ValidationError:
            raise CliError(
                "RUNTIME_RESPONSE_INVALID",
                "The recovery preview is invalid. No change was submitted.",
                exit_code=UNAVAILABLE,
            ) from None
        if args.preview or preview.eligible_rows == 0:
            if ctx.json:
                write_json(raw)
            elif not ctx.quiet:
                print(_preview_text(preview))
            return 0
        if not args.yes:
            if not interactive:
                raise CliError(
                    "CONFIRMATION_REQUIRED",
                    "Review with --preview, then use --yes "
                    "to enable automatic chunking and retry eligible failures.",
                    exit_code=USAGE,
                )
            print(_preview_text(preview), file=sys.stderr)
            print(
                "Enable automatic chunking and retry eligible failures? [y/N] ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            if sys.stdin.readline().strip().lower() not in {"y", "yes"}:
                if not ctx.quiet:
                    print("Cancelled. No changes submitted.")
                return 0
        try:
            result = request(
                ctx,
                project_id,
                "context:manage",
                "POST",
                path,
                json={"action": "enable_chunking", "expected_version": preview.expected_version},
                read_only_retry=False,
                allow_auth_replay=False,
                timeout=130,
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            raise CliError(
                "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED",
                "The recovery result could not be confirmed. The request was not "
                "repeated. Inspect embeddings get and recover-oversized --preview "
                "before deciding whether another submission is needed.",
                exit_code=UNAVAILABLE,
            ) from None
        except CliError as exc:
            if exc.status_code is not None and (exc.status_code >= 500 or exc.status_code == 408):
                raise CliError(
                    "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED",
                    "The server could not confirm recovery. Inspect the configuration "
                    "before retrying; the request was not repeated.",
                    exit_code=UNAVAILABLE,
                    request_id=exc.request_id,
                ) from None
            if exc.code == "EMBEDDING_CONFIGURATION_CONFLICT":
                if interactive and not args.yes and attempt < 2:
                    print(
                        "Configuration changed. Refreshing the preview for confirmation.",
                        file=sys.stderr,
                    )
                    continue
                exc.message = "Configuration changed after preview. No automatic retry was made. "
                exc.message += "Review a fresh preview before running recovery again."
            raise
        try:
            completed = EmbeddingChunkingRecovery.model_validate(result)
        except ValidationError:
            raise CliError(
                "EMBEDDING_RECOVERY_OUTCOME_UNCONFIRMED",
                "The server response was invalid after submission. Inspect the "
                "configuration before retrying; the request was not repeated.",
                exit_code=UNAVAILABLE,
            ) from None
        if ctx.json:
            write_json(result)
        elif not ctx.quiet:
            print(
                f"{completed.retried_rows} failed documents queued for retry. "
                "Generation has not necessarily completed."
            )
            print(
                "Paused configurations remain paused. Use embeddings get to check progress "
                "and embeddings resume when ready."
            )
        return 0


def watch(ctx, args, project_id):
    deadline = time.monotonic() + args.timeout
    last = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CliError(
                    "EMBEDDING_WATCH_TIMEOUT",
                    "Monitoring timed out; processing continues on the server.",
                    exit_code=UNAVAILABLE,
                )
            value = request(
                ctx,
                project_id,
                "context:read",
                "GET",
                f"/embeddings/configurations/{args.configuration_id}",
                timeout=min(30, remaining),
            )
            p = value.get("progress", {})
            summary = render_summary(value)
            if not ctx.json and not ctx.quiet and summary != last:
                print(summary, flush=True)
            last = summary
            if value.get("status") == "current" and all(
                p.get(key) == 0
                for key in (
                    "pending",
                    "processing",
                    "failed",
                    "uncertain",
                    "context_pending",
                    "context_failed",
                )
            ):
                if ctx.json:
                    write_json(value)
                return 0
            manual = value.get("settings", {}).get("mode") == "manual"
            if value.get("status") in {"paused", "removed", "quota_exhausted"} or (
                p.get("failed")
                or p.get("uncertain")
                or manual
                and value.get("initial_scan_complete")
                and p.get("pending")
                and not value.get("run_requested")
            ):
                raise CliError(
                    "EMBEDDING_WATCH_ACTION_REQUIRED",
                    "Processing needs attention. Inspect embeddings get before "
                    "resuming, retrying, or reconciling.",
                    exit_code=CONFLICT,
                    details={"status": value.get("status"), "progress": p},
                )
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    except KeyboardInterrupt:
        raise CliError(
            "EMBEDDING_WATCH_INTERRUPTED",
            "Monitoring stopped; server processing was not cancelled.",
            exit_code=130,
        ) from None
    except (httpx.TimeoutException, httpx.NetworkError):
        raise CliError(
            "EMBEDDING_WATCH_UNAVAILABLE",
            "Could not read progress. Monitoring stopped; server processing continues.",
            exit_code=UNAVAILABLE,
        ) from None
