from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any
from urllib.parse import quote, urlencode

from polygres_cli.cli_errors import CliError, UsageError

SNAPSHOT_VERSION = 1
SNAPSHOT_RESOURCE = "openapi/control-plane-v1.json"
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_METHOD_KEYS = {method.lower() for method in HTTP_METHODS}
_PARAMETER_LOCATIONS = {"path", "query", "header"}
_FORBIDDEN_HEADERS = {
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "proxy-authorization",
    "transfer-encoding",
}


@dataclass(frozen=True)
class ApiOperation:
    route: str
    schema_path: str
    method: str
    operation_id: str
    summary: str
    tags: tuple[str, ...]
    operation: dict[str, Any]
    path_item: dict[str, Any]


@dataclass(frozen=True)
class ApiRequestPlan:
    operation: ApiOperation
    path: str
    query: tuple[tuple[str, str], ...]
    headers: dict[str, str]
    body: Any
    has_body: bool

    @property
    def request_path(self) -> str:
        query = urlencode(self.query)
        return f"{self.path}?{query}" if query else self.path

    def output(self) -> dict[str, Any]:
        rendered_query: dict[str, Any] = {}
        for key, value in self.query:
            existing = rendered_query.get(key)
            if existing is None:
                rendered_query[key] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                rendered_query[key] = [existing, value]
        payload: dict[str, Any] = {
            "route": self.operation.route,
            "operation_id": self.operation.operation_id,
            "method": self.operation.method,
            "path": self.path,
            "query": rendered_query,
            "headers": self.headers,
        }
        if self.has_body:
            payload["body"] = self.body
        return payload


@lru_cache(maxsize=1)
def load_openapi_snapshot() -> dict[str, Any]:
    resource = files("polygres_cli").joinpath(SNAPSHOT_RESOURCE)
    try:
        with resource.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliError(
            "OPENAPI_SNAPSHOT_INVALID",
            "The bundled OpenAPI snapshot could not be loaded.",
        ) from exc
    if not isinstance(document, dict):
        raise CliError("OPENAPI_SNAPSHOT_INVALID", "The bundled OpenAPI snapshot is invalid.")
    if document.get("x-polygres-cli-snapshot-version") != SNAPSHOT_VERSION:
        raise CliError(
            "OPENAPI_SNAPSHOT_INVALID",
            "The bundled OpenAPI snapshot version is not supported.",
        )
    if not isinstance(document.get("openapi"), str) or not isinstance(
        document.get("paths"), dict
    ):
        raise CliError("OPENAPI_SNAPSHOT_INVALID", "The bundled OpenAPI snapshot is incomplete.")
    return document


def list_api_operations(*, method: str | None = None) -> list[ApiOperation]:
    selected_method = _normalize_method(method) if method else None
    document = load_openapi_snapshot()
    operations: list[ApiOperation] = []
    for schema_path, raw_path_item in document["paths"].items():
        if not isinstance(schema_path, str) or not schema_path.startswith("/v1/"):
            continue
        if not isinstance(raw_path_item, dict):
            continue
        route = schema_path.removeprefix("/v1")
        for method_key, raw_operation in raw_path_item.items():
            if method_key not in _METHOD_KEYS or not isinstance(raw_operation, dict):
                continue
            operation_method = method_key.upper()
            if selected_method and operation_method != selected_method:
                continue
            operation_id = raw_operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise CliError(
                    "OPENAPI_SNAPSHOT_INVALID",
                    f"The bundled OpenAPI operation {operation_method} {schema_path} "
                    "has no operationId.",
                )
            tags = raw_operation.get("tags")
            operations.append(
                ApiOperation(
                    route=route,
                    schema_path=schema_path,
                    method=operation_method,
                    operation_id=operation_id,
                    summary=str(raw_operation.get("summary") or ""),
                    tags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
                    operation=raw_operation,
                    path_item=raw_path_item,
                )
            )
    operations.sort(key=lambda item: (item.route, HTTP_METHODS.index(item.method)))
    return operations


def resolve_api_operation(route: str, *, method: str | None = None) -> ApiOperation:
    normalized_route = _normalize_route_identifier(route)
    requested_method = _normalize_method(method) if method else None
    operations = list_api_operations()
    candidates = [
        operation
        for operation in operations
        if normalized_route in {operation.route, operation.operation_id}
    ]
    if not candidates:
        raise UsageError(
            f"Unknown API route: {route}",
            code="API_ROUTE_NOT_FOUND",
        )
    if requested_method:
        matching = [operation for operation in candidates if operation.method == requested_method]
        if not matching:
            supported = sorted({operation.method for operation in candidates})
            raise UsageError(
                f"{requested_method} is not available for API route {route}. "
                f"Choose one of: {', '.join(supported)}.",
                code="API_METHOD_NOT_ALLOWED",
            )
        return matching[0]
    if len(candidates) > 1:
        supported = sorted({operation.method for operation in candidates})
        raise UsageError(
            f"API route {route} supports multiple methods. "
            f"Pass --method with one of: {', '.join(supported)}.",
            code="API_METHOD_REQUIRED",
        )
    return candidates[0]


def api_route_rows(*, method: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "route": operation.route,
            "method": operation.method,
            "operation_id": operation.operation_id,
            "summary": operation.summary,
            "tags": list(operation.tags),
        }
        for operation in list_api_operations(method=method)
    ]


def inspect_api_operation(operation: ApiOperation) -> dict[str, Any]:
    document = load_openapi_snapshot()
    parameters = [
        _resolve_object(document, parameter)
        for parameter in _operation_parameters(operation)
    ]
    request_body = operation.operation.get("requestBody")
    if isinstance(request_body, dict):
        request_body = _resolve_object(document, request_body)
    else:
        request_body = None
    responses = operation.operation.get("responses")
    if not isinstance(responses, dict):
        responses = {}
    schema_material = {
        "parameters": parameters,
        "request_body": request_body,
        "responses": responses,
    }
    referenced_schemas = _referenced_component_schemas(document, schema_material)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "openapi_version": document["openapi"],
        "route": operation.route,
        "schema_path": operation.schema_path,
        "method": operation.method,
        "operation_id": operation.operation_id,
        "summary": operation.summary,
        "description": operation.operation.get("description"),
        "tags": list(operation.tags),
        "security": operation.operation.get("security"),
        **schema_material,
        "components": {"schemas": referenced_schemas},
    }


def build_api_request_plan(
    operation: ApiOperation,
    raw_parameters: list[str],
    *,
    body: Any = None,
    body_provided: bool = False,
    default_project_id: str | None = None,
) -> ApiRequestPlan:
    document = load_openapi_snapshot()
    declarations = [
        _resolve_object(document, parameter)
        for parameter in _operation_parameters(operation)
    ]
    parsed_inputs = _parse_parameter_inputs(raw_parameters)
    if default_project_id and not _has_parameter_input(parsed_inputs, "path", "project_id"):
        parsed_inputs.append((None, "project_id", default_project_id))

    values: dict[tuple[str, str], list[Any]] = {}
    for requested_location, name, raw_value in parsed_inputs:
        declaration = _select_parameter_declaration(
            declarations,
            requested_location=requested_location,
            name=name,
        )
        location = str(declaration["in"])
        declared_name = str(declaration["name"])
        schema = declaration.get("schema")
        if not isinstance(schema, dict):
            schema = {}
        parsed_value = _parse_parameter_value(document, schema, raw_value)
        values.setdefault((location, declared_name), []).append(parsed_value)

    for declaration in declarations:
        if not declaration.get("required"):
            continue
        key = (str(declaration.get("in")), str(declaration.get("name")))
        if key not in values:
            raise UsageError(
                f"Missing required {key[0]} parameter: {key[1]}",
                code="API_PARAMETER_REQUIRED",
            )

    rendered_path = operation.route
    query: list[tuple[str, str]] = []
    headers: dict[str, str] = {}
    for declaration in declarations:
        location = str(declaration.get("in"))
        name = str(declaration.get("name"))
        supplied = values.get((location, name))
        if not supplied:
            continue
        schema = declaration.get("schema")
        schema = schema if isinstance(schema, dict) else {}
        if _schema_type(document, schema) == "array":
            if len(supplied) == 1 and isinstance(supplied[0], list):
                supplied = supplied[0]
            errors = _schema_errors(document, schema, supplied, path=f"parameter {name}")
            if errors:
                raise UsageError(errors[0], code="API_PARAMETER_INVALID")
        elif len(supplied) > 1:
            raise UsageError(
                f"API parameter {name} may only be supplied once.",
                code="API_PARAMETER_DUPLICATE",
            )
        if location == "path":
            if len(supplied) != 1 or isinstance(supplied[0], (dict, list)):
                raise UsageError(
                    f"Path parameter {name} must be a scalar value.",
                    code="API_PARAMETER_INVALID",
                )
            rendered_path = rendered_path.replace(
                "{" + name + "}",
                _quote_path_parameter(name, supplied[0]),
            )
        elif location == "query":
            query.extend((name, _serialize_parameter(item)) for item in supplied)
        elif location == "header":
            if name.lower() in _FORBIDDEN_HEADERS:
                raise UsageError(
                    f"Header parameter {name} cannot be set by api request.",
                    code="API_PARAMETER_INVALID",
                )
            headers[name] = ",".join(_serialize_parameter(item) for item in supplied)

    if re.search(r"\{[^{}]+\}", rendered_path):
        raise UsageError(
            f"Not all path parameters were supplied for API route {operation.route}.",
            code="API_PARAMETER_REQUIRED",
        )
    _validate_request_body(
        document,
        operation,
        body=body,
        body_provided=body_provided,
    )
    return ApiRequestPlan(
        operation=operation,
        path=rendered_path,
        query=tuple(query),
        headers=headers,
        body=body,
        has_body=body_provided,
    )


def parse_json_body(raw: str, *, source: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(
            f"{source} does not contain valid JSON: {exc.msg}.",
            code="API_BODY_INVALID",
        ) from exc


def _normalize_route_identifier(route: str) -> str:
    value = route.strip()
    if not value:
        raise UsageError("API route cannot be empty.", code="API_ROUTE_NOT_FOUND")
    if (
        "://" in value
        or "?" in value
        or "#" in value
        or any(character.isspace() for character in value)
    ):
        raise UsageError(
            "API routes must be bundled route names, not URLs or query strings.",
            code="API_ROUTE_NOT_FOUND",
        )
    if value.startswith("/v1/"):
        value = value.removeprefix("/v1")
    elif value.startswith("/"):
        pass
    elif "/" in value:
        value = "/" + value
    return value.rstrip("/") or "/"


def _normalize_method(method: str) -> str:
    value = method.strip().upper()
    if value not in HTTP_METHODS:
        raise UsageError(
            f"Unsupported HTTP method: {method}. Choose one of: {', '.join(HTTP_METHODS)}.",
            code="API_METHOD_NOT_ALLOWED",
        )
    return value


def _operation_parameters(operation: ApiOperation) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for source in (
        operation.path_item.get("parameters"),
        operation.operation.get("parameters"),
    ):
        if isinstance(source, list):
            parameters.extend(item for item in source if isinstance(item, dict))
    return parameters


def _parse_parameter_inputs(raw_parameters: list[str]) -> list[tuple[str | None, str, str]]:
    parsed: list[tuple[str | None, str, str]] = []
    for raw in raw_parameters:
        if "=" not in raw:
            raise UsageError(
                f"API parameter must use NAME=VALUE: {raw}",
                code="API_PARAMETER_INVALID",
            )
        raw_name, value = raw.split("=", 1)
        raw_name = raw_name.strip()
        location: str | None = None
        name = raw_name
        if ":" in raw_name:
            possible_location, possible_name = raw_name.split(":", 1)
            if possible_location in _PARAMETER_LOCATIONS:
                location = possible_location
                name = possible_name
        if not name:
            raise UsageError("API parameter name cannot be empty.", code="API_PARAMETER_INVALID")
        parsed.append((location, name, value))
    return parsed


def _has_parameter_input(
    parsed_inputs: list[tuple[str | None, str, str]],
    location: str,
    name: str,
) -> bool:
    return any(
        input_name == name and input_location in {None, location}
        for input_location, input_name, _ in parsed_inputs
    )


def _select_parameter_declaration(
    declarations: list[dict[str, Any]],
    *,
    requested_location: str | None,
    name: str,
) -> dict[str, Any]:
    matches = [
        declaration
        for declaration in declarations
        if declaration.get("in") in _PARAMETER_LOCATIONS
        and (
            str(declaration.get("name")).lower() == name.lower()
            if declaration.get("in") == "header"
            else declaration.get("name") == name
        )
        and (requested_location is None or declaration.get("in") == requested_location)
    ]
    if not matches:
        allowed = sorted(
            f"{declaration.get('in')}:{declaration.get('name')}"
            for declaration in declarations
            if declaration.get("in") in _PARAMETER_LOCATIONS
        )
        suffix = f" Available parameters: {', '.join(allowed)}." if allowed else ""
        raise UsageError(
            f"Unknown API parameter: {name}.{suffix}",
            code="API_PARAMETER_NOT_FOUND",
        )
    if len(matches) > 1:
        locations = ", ".join(sorted(str(match["in"]) for match in matches))
        raise UsageError(
            f"API parameter {name} is ambiguous. Prefix it with one of: {locations}.",
            code="API_PARAMETER_AMBIGUOUS",
        )
    return matches[0]


def _parse_parameter_value(document: dict[str, Any], schema: dict[str, Any], raw: str) -> Any:
    schema_type = _schema_type(document, schema)
    try:
        if schema_type == "boolean":
            if raw.lower() not in {"true", "false"}:
                raise ValueError
            value: Any = raw.lower() == "true"
        elif schema_type == "integer":
            value = int(raw)
        elif schema_type == "number":
            value = float(raw)
        elif schema_type == "array":
            if raw.lstrip().startswith("["):
                value = json.loads(raw)
            else:
                resolved = _resolve_object(document, schema)
                item_schema = resolved.get("items")
                item_schema = item_schema if isinstance(item_schema, dict) else {}
                return _parse_parameter_value(document, item_schema, raw)
        elif schema_type == "object":
            value = json.loads(raw)
        else:
            value = raw
    except (ValueError, json.JSONDecodeError) as exc:
        raise UsageError(
            f"API parameter value {raw!r} is not a valid {schema_type or 'schema'} value.",
            code="API_PARAMETER_INVALID",
        ) from exc
    errors = _schema_errors(document, schema, value, path="parameter")
    if errors:
        raise UsageError(errors[0], code="API_PARAMETER_INVALID")
    return value


def _schema_type(document: dict[str, Any], schema: dict[str, Any]) -> str | None:
    resolved = _resolve_object(document, schema)
    raw_type = resolved.get("type")
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        concrete = [item for item in raw_type if item != "null"]
        return concrete[0] if len(concrete) == 1 and isinstance(concrete[0], str) else None
    for keyword in ("anyOf", "oneOf"):
        options = resolved.get(keyword)
        if isinstance(options, list):
            types = {
                candidate
                for option in options
                if isinstance(option, dict)
                and (candidate := _schema_type(document, option)) is not None
                and candidate != "null"
            }
            if len(types) == 1:
                return types.pop()
    if "properties" in resolved:
        return "object"
    if "items" in resolved:
        return "array"
    return None


def _serialize_parameter(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _quote_path_parameter(name: str, value: Any) -> str:
    rendered = _serialize_parameter(value)
    if rendered in {".", ".."} or any(character in rendered for character in "/\\?#"):
        raise UsageError(
            f"Path parameter {name} contains a path separator or reserved path value.",
            code="API_PARAMETER_INVALID",
        )
    return quote(rendered, safe="")


def _validate_request_body(
    document: dict[str, Any],
    operation: ApiOperation,
    *,
    body: Any,
    body_provided: bool,
) -> None:
    raw_request_body = operation.operation.get("requestBody")
    if not isinstance(raw_request_body, dict):
        if body_provided:
            raise UsageError(
                f"{operation.method} {operation.route} does not declare a request body.",
                code="API_BODY_NOT_ALLOWED",
            )
        return
    request_body = _resolve_object(document, raw_request_body)
    if request_body.get("required") and not body_provided:
        raise UsageError(
            f"{operation.method} {operation.route} requires a JSON request body.",
            code="API_BODY_REQUIRED",
        )
    if not body_provided:
        return
    content = request_body.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("application/json"), dict):
        supported = sorted(content) if isinstance(content, dict) else []
        suffix = f" Declared content types: {', '.join(supported)}." if supported else ""
        raise UsageError(
            f"{operation.method} {operation.route} does not accept a JSON request body.{suffix}",
            code="API_BODY_NOT_ALLOWED",
        )
    schema = content["application/json"].get("schema")
    if not isinstance(schema, dict):
        return
    errors = _schema_errors(document, schema, body, path="body")
    if errors:
        raise UsageError(errors[0], code="API_BODY_INVALID")


def _schema_errors(
    document: dict[str, Any],
    schema: dict[str, Any],
    value: Any,
    *,
    path: str,
) -> list[str]:
    resolved = _resolve_object(document, schema)
    for keyword in ("anyOf", "oneOf"):
        options = resolved.get(keyword)
        if isinstance(options, list):
            option_errors = [
                _schema_errors(document, option, value, path=path)
                for option in options
                if isinstance(option, dict)
            ]
            if any(not errors for errors in option_errors):
                break
            return [f"{path} does not match any allowed schema."]
    all_of = resolved.get("allOf")
    if isinstance(all_of, list):
        for option in all_of:
            if isinstance(option, dict):
                errors = _schema_errors(document, option, value, path=path)
                if errors:
                    return errors

    allowed_types = resolved.get("type")
    if isinstance(allowed_types, str):
        allowed_types = [allowed_types]
    if isinstance(allowed_types, list) and not _matches_any_type(value, allowed_types):
        return [f"{path} must be {_format_types(allowed_types)}."]
    if "enum" in resolved and isinstance(resolved["enum"], list) and value not in resolved["enum"]:
        return [f"{path} must be one of: {', '.join(map(str, resolved['enum']))}."]
    if "const" in resolved and value != resolved["const"]:
        return [f"{path} must equal {resolved['const']!r}."]

    schema_type = _schema_type(document, resolved)
    if schema_type == "object" and isinstance(value, dict):
        required = resolved.get("required")
        if isinstance(required, list):
            missing = [name for name in required if name not in value]
            if missing:
                return [f"{path} is missing required field: {missing[0]}."]
        properties = resolved.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        if resolved.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                return [f"{path} contains unknown field: {unknown[0]}."]
        for name, item in value.items():
            child_schema = properties.get(name)
            if not isinstance(child_schema, dict):
                additional = resolved.get("additionalProperties")
                child_schema = additional if isinstance(additional, dict) else None
            if child_schema is not None:
                errors = _schema_errors(document, child_schema, item, path=f"{path}.{name}")
                if errors:
                    return errors
    if schema_type == "array" and isinstance(value, list):
        minimum = resolved.get("minItems")
        maximum = resolved.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            return [f"{path} must contain at least {minimum} items."]
        if isinstance(maximum, int) and len(value) > maximum:
            return [f"{path} must contain no more than {maximum} items."]
        item_schema = resolved.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors = _schema_errors(document, item_schema, item, path=f"{path}[{index}]")
                if errors:
                    return errors
    if schema_type == "string" and isinstance(value, str):
        minimum = resolved.get("minLength")
        maximum = resolved.get("maxLength")
        pattern = resolved.get("pattern")
        if isinstance(minimum, int) and len(value) < minimum:
            return [f"{path} must contain at least {minimum} characters."]
        if isinstance(maximum, int) and len(value) > maximum:
            return [f"{path} must contain no more than {maximum} characters."]
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            return [f"{path} does not match the required pattern."]
    if schema_type in {"integer", "number"} and isinstance(value, (int, float)):
        minimum = resolved.get("minimum")
        maximum = resolved.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            return [f"{path} must be at least {minimum}."]
        if isinstance(maximum, (int, float)) and value > maximum:
            return [f"{path} must be no greater than {maximum}."]
    return []


def _matches_any_type(value: Any, allowed_types: list[Any]) -> bool:
    for allowed in allowed_types:
        if allowed == "null" and value is None:
            return True
        if allowed == "object" and isinstance(value, dict):
            return True
        if allowed == "array" and isinstance(value, list):
            return True
        if allowed == "string" and isinstance(value, str):
            return True
        if allowed == "boolean" and isinstance(value, bool):
            return True
        if allowed == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if (
            allowed == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return True
    return False


def _format_types(types: list[Any]) -> str:
    names = [str(item) for item in types]
    if len(names) == 1:
        return names[0]
    return f"one of: {', '.join(names)}"


def _resolve_object(document: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    ref = value.get("$ref")
    if not isinstance(ref, str):
        return value
    if not ref.startswith("#/"):
        raise CliError(
            "OPENAPI_SNAPSHOT_INVALID",
            f"The bundled OpenAPI snapshot contains an external reference: {ref}",
        )
    current: Any = document
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise CliError(
                "OPENAPI_SNAPSHOT_INVALID",
                f"The bundled OpenAPI snapshot contains an unresolved reference: {ref}",
            )
        current = current[token]
    if not isinstance(current, dict):
        raise CliError(
            "OPENAPI_SNAPSHOT_INVALID",
            f"The bundled OpenAPI reference is not an object: {ref}",
        )
    return current


def _referenced_component_schemas(
    document: dict[str, Any],
    value: Any,
) -> dict[str, Any]:
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return {}
    pending = list(_schema_ref_names(value))
    selected: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        schema = schemas.get(name)
        if not isinstance(schema, dict):
            continue
        selected[name] = schema
        pending.extend(_schema_ref_names(schema) - set(selected))
    return {name: selected[name] for name in sorted(selected)}


def _schema_ref_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        prefix = "#/components/schemas/"
        if isinstance(ref, str) and ref.startswith(prefix):
            names.add(ref.removeprefix(prefix))
        for item in value.values():
            names.update(_schema_ref_names(item))
    elif isinstance(value, list):
        for item in value:
            names.update(_schema_ref_names(item))
    return names
