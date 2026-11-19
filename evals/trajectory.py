"""
Trajectory logging and tool-argument validation for the eval runner.

Changes from the originals:
  * RUN_OUTCOMES gains `empty_answer`.
  * validate_tool_arguments takes the tool's JSON-schema dict (the
    tool_bridge.list_tools() "parameters" value) instead of a Tool object.
  * Array items are checked against `items`, resolving `$ref` from `$defs`.
  * A null for a parameter that is not required is accepted: tool_bridge
    flattens Optional[...] anyOf and drops the null branch, but the tool itself
    accepts None, so rejecting it would count a legal call as a fabrication.

One JSONL file per run, one JSON object per event. Event `type` values used:
run_start, tool_call, tool_result, tool_validation_error, retry, run_end.
(`prompt`, `completion` and `truncated` writers are kept for format parity.)
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Trajectory schema note: run_end.outcome is the machine-readable stop/failure
# taxonomy. Keep this list in sync with any analysis scripts; run_end.reason
# remains the human-readable prose explanation.
RUN_OUTCOMES = {
    "completed",       # The model attempted the task and gave a final answer.
    "non_attempt",     # The model answered without ever calling a warranted tool.
    "truncated",       # Output max_tokens cap hit before the completion finished.
    "turn_limit",      # The agent exhausted max_turns before a final answer.
    "token_limit",     # Cumulative model-reported token usage crossed the run budget.
    "no_progress",     # The same tool call with the same args repeated too often.
    "tool_error_loop", # Reserved for repeated tool-error-specific stall detection.
    "harness_error",   # The harness itself raised while running/logging/grading.
    "empty_answer",    # The model returned neither text nor a tool call.
}


def _make_run_id() -> str:
    """Sortable, unique run id: UTC timestamp, microseconds within the second,
    and a short random tail. Lexicographic order is chronological order, so
    `ls | sort` finds the latest run without mtimes. The random tail matters:
    log files open in append mode, so two runs that ever shared an id would
    interleave their events in one file."""
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}Z-{now.microsecond:06d}-{uuid.uuid4().hex[:4]}"


def _json_safe(obj: Any) -> Any:
    """Best-effort conversion of dataclasses / arbitrary objects to JSON-safe values."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class TrajectoryLogger:
    def __init__(self, out_dir: Path, run_id: str | None = None):
        out_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or _make_run_id()
        self.path = out_dir / f"{self.run_id}.jsonl"
        self._f = open(self.path, "a", encoding="utf-8")
        self._turn = 0

    def _write(self, event_type: str, **fields):
        record = {
            "run_id": self.run_id,
            "ts": time.time(),
            "turn": self._turn,
            "type": event_type,
            **{k: _json_safe(v) for k, v in fields.items()},
        }
        self._f.write(json.dumps(record) + "\n")
        self._f.flush()

    def run_start(self, task_id: str, backend: str, model: str, config: dict):
        self._write("run_start", task_id=task_id, backend=backend, model=model, config=config)

    def prompt(self, messages: list[dict], system: str | None):
        self._write("prompt", messages=messages, system=system)

    def completion(self, response):
        self._write(
            "completion",
            content=response.content,
            tool_calls=response.tool_calls,
            stop_reason=response.stop_reason,
            usage=response.usage,
            latency_s=response.latency_s,
        )

    def tool_call(self, name: str, arguments: dict):
        self._write("tool_call", name=name, arguments=arguments)

    def tool_result(self, name: str, result: str | None, error: str | None, latency_s: float):
        self._write("tool_result", name=name, result=result, error=error, latency_s=latency_s)

    def tool_validation_error(
        self,
        name,
        rule,
        message,
        arguments,
        *,
        parameter=None,
        expected_type=None,
        actual_type=None,
    ):
        self._write(
            "tool_validation_error",
            name=name,
            rule=rule,
            message=message,
            parameter=parameter,
            expected_type=expected_type,
            actual_type=actual_type,
            arguments=arguments,
        )

    def retry(
        self,
        reason: str,
        *,
        status: int | str,
        attempt: int,
        max_attempts: int,
        delay_s: float,
        attempt_duration_s: float,
    ):
        """Write a retry event with fields suitable for grouping by failure.

        Schema note: `status` is an HTTP status code or exception class name;
        `attempt`, `max_attempts`, and `delay_s` describe this scheduled retry.
        `attempt_duration_s` is how long the failed attempt itself ran, so a
        read-timeout (near the client timeout) is distinguishable from an
        instant connection refusal. `reason` remains human-readable context,
        not the analysis interface.
        """
        self._write(
            "retry",
            reason=reason,
            status=status,
            attempt=attempt,
            max_attempts=max_attempts,
            delay_s=delay_s,
            attempt_duration_s=attempt_duration_s,
        )

    def truncated(self, reason: str):
        self._write("truncated", reason=reason)

    def next_turn(self):
        self._turn += 1

    def run_end(
        self,
        success: bool,
        reason: str,
        total_turns: int,
        wall_clock_s: float,
        outcome: str,
        input_tokens: int,
        output_tokens: int,
        peak_input_tokens: int,
        total_tokens: int,
        completions: int,
        graded_ok: bool,
    ):
        if outcome not in RUN_OUTCOMES:
            raise ValueError(f"unknown run outcome: {outcome!r}")
        self._write(
            "run_end",
            success=success,
            outcome=outcome,
            reason=reason,
            total_turns=total_turns,
            wall_clock_s=wall_clock_s,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            peak_input_tokens=peak_input_tokens,
            total_tokens=total_tokens,
            completions=completions,
            graded_ok=graded_ok,
        )
        self._f.close()


@dataclass(frozen=True)
class ToolValidationError:
    """A rejected tool call, kept structured for trajectory analysis."""

    rule: str
    message: str
    parameter: str | None = None
    expected_type: str | None = None
    actual_type: str | None = None


def validate_tool_arguments(schema: dict[str, Any], arguments: Any) -> ToolValidationError | None:
    """Validate the small JSON-Schema subset the chat tools use.

    Covers object/properties/required/type, array `items`, and `$ref` into the
    schema's `$defs`, so malformed model calls are caught before they reach a
    tool body. A schema using any other keyword needs support added here first.
    Unknown parameters are rejected at the top level only: the sanitized
    schemas drop additionalProperties, so nested extras cannot be judged.
    """
    if not isinstance(arguments, dict):
        return ToolValidationError(
            rule="wrong_type",
            message="tool arguments must be an object",
            expected_type="object",
            actual_type=type(arguments).__name__,
        )

    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            return ToolValidationError(
                rule="missing_required_param",
                message=f"missing required parameter: {name}",
                parameter=name,
            )

    required = set(schema.get("required", []))
    defs = schema.get("$defs", {})
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if property_schema is None:
            return ToolValidationError(
                rule="unknown_param",
                message=f"unknown parameter: {name}",
                parameter=name,
            )
        if value is None and name not in required:
            continue
        error = _validate_value(property_schema, value, name, defs)
        if error:
            return error
    return None


def _resolve_ref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Follow `$ref: "#/$defs/<Name>"`; anything unresolvable is left as-is."""
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
        return node
    return defs.get(ref[len("#/$defs/"):], node)


def _validate_value(node: dict[str, Any], value: Any, path: str, defs: dict[str, Any]) -> ToolValidationError | None:
    node = _resolve_ref(node, defs)
    expected_type = node.get("type")
    if expected_type and not _matches_json_type(value, expected_type):
        return ToolValidationError(
            rule="wrong_type",
            message=f"parameter {path} must be {expected_type}, got {type(value).__name__}",
            parameter=path,
            expected_type=expected_type,
            actual_type=type(value).__name__,
        )

    if expected_type == "array" and isinstance(node.get("items"), dict):
        for index, item in enumerate(value):
            error = _validate_value(node["items"], item, f"{path}[{index}]", defs)
            if error:
                return error

    if expected_type == "object":
        properties = node.get("properties", {})
        for name in node.get("required", []):
            if name not in value:
                return ToolValidationError(
                    rule="missing_required_param",
                    message=f"missing required parameter: {path}.{name}",
                    parameter=f"{path}.{name}",
                )
        for name, child in value.items():
            if name in properties and not (child is None and name not in node.get("required", [])):
                error = _validate_value(properties[name], child, f"{path}.{name}", defs)
                if error:
                    return error
    return None


def _matches_json_type(value: Any, expected_type: str) -> bool:
    """Map the JSON types used in tool schemas to Python values.

    `bool` does not match integer/number: Python makes it an int subclass,
    while JSON Schema treats booleans as a separate type.
    """
    matches = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }
    return matches.get(expected_type, False)
