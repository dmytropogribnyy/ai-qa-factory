"""Phase 5M — API Contract Importer.

Parses OpenAPI (JSON/YAML) and Postman collection specs into a structured
APIContractReport with per-endpoint safety classification.

Safety rules:
- No network calls — spec file must be local
- No credential extraction from spec files
- No destructive API calls generated or executed
- All endpoints classified before any test generation
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from core.schemas.api_contract import (
    APIContractReport,
    APIEndpoint,
    APIParameter,
    AuthRequirement,
    SAFE_METHODS,
)

# ---------------------------------------------------------------------------
# Safety classification
# ---------------------------------------------------------------------------

_BLOCKED_PATH_TERMS = (
    "delete", "remove", "destroy", "purge",
    "payment", "charge", "billing", "refund",
    "admin", "superuser",
    "deactivate", "disable", "ban", "suspend",
)

_RISKY_PATH_TERMS = (
    "create", "update", "edit", "modify", "reset", "clear",
    "purchase", "checkout", "account", "export", "bulk", "batch",
    "users", "orders",
)


def classify_endpoint(method: str, path: str) -> Tuple[str, str]:
    """Return (safety_classification, reason) for a given HTTP method + path."""
    method = method.upper()
    path_lower = path.lower()

    # DELETE is always blocked — inherently destructive regardless of path
    if method == "DELETE":
        return "blocked_by_default", f"method={method} is destructive by default"

    # Blocked: unsafe method + blocked path term (payment, billing, admin, etc.)
    if method not in SAFE_METHODS:
        for term in _BLOCKED_PATH_TERMS:
            pattern = rf"(^|[/_-]){re.escape(term)}([/_-]|$)"
            if re.search(pattern, path_lower):
                return "blocked_by_default", f"method={method} path contains '{term}'"

    # Requires approval: any remaining non-safe method
    if method not in SAFE_METHODS:
        for term in _RISKY_PATH_TERMS:
            pattern = rf"(^|[/_-]){re.escape(term)}([/_-]|$|\d)"
            if re.search(pattern, path_lower):
                return "requires_approval", f"method={method} path contains '{term}'"
        return "requires_approval", f"method={method} requires approval"

    # Safe: GET/HEAD/OPTIONS with non-risky path
    for term in _BLOCKED_PATH_TERMS:
        pattern = rf"(^|[/_-]){re.escape(term)}([/_-]|$)"
        if re.search(pattern, path_lower):
            return "requires_approval", f"method={method} but path contains '{term}'"

    return "safe_readonly", f"method={method} read-only"


# ---------------------------------------------------------------------------
# OpenAPI parser
# ---------------------------------------------------------------------------

def _load_file(path: Path) -> Tuple[Optional[dict], str, List[str]]:
    """Load a spec file as dict. Returns (data, detected_format, errors)."""
    errors: List[str] = []
    suffix = path.suffix.lower()

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "unknown", [f"Cannot read file: {exc}"]

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import]
        except ImportError:
            return None, "openapi_yaml", [
                "YAML parsing requires pyyaml. Install with: pip install pyyaml"
            ]
        try:
            data = yaml.safe_load(raw)
            if isinstance(data, dict):
                return data, "openapi_yaml", errors
            errors.append("YAML parsed but root is not a mapping")
            return None, "openapi_yaml", errors
        except Exception as exc:
            errors.append(f"YAML parse error: {exc}")
            return None, "openapi_yaml", errors

    # Try JSON first (covers .json and format-ambiguous files)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            # Distinguish Postman from OpenAPI
            if "info" in data and "schema" in data.get("info", {}):
                return data, "postman_collection", errors
            return data, "openapi_json", errors
        errors.append("JSON parsed but root is not a mapping")
        return None, "openapi_json", errors
    except json.JSONDecodeError:
        pass

    # Try YAML as fallback for non-.yaml files (e.g. .yml without extension detection)
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            return data, "openapi_yaml", errors
    except ImportError:
        errors.append("YAML parsing requires pyyaml. Install with: pip install pyyaml")
    except Exception:
        pass

    errors.append("Could not parse file as JSON or YAML")
    return None, "unknown", errors


def _extract_auth_requirements(spec: dict) -> List[AuthRequirement]:
    """Extract security scheme definitions from an OpenAPI spec."""
    reqs: List[AuthRequirement] = []
    components = spec.get("components", spec.get("securityDefinitions", {}))
    security_schemes = components.get("securitySchemes", components)
    if not isinstance(security_schemes, dict):
        return reqs
    for name, scheme in security_schemes.items():
        if not isinstance(scheme, dict):
            continue
        reqs.append(AuthRequirement(
            scheme_name=str(name),
            scheme_type=str(scheme.get("type", "unknown")),
            description=str(scheme.get("description", "")),
            scopes=list(scheme.get("flows", {}).keys()) if "flows" in scheme else [],
        ))
    return reqs


def _parse_openapi(spec: dict, source_format: str) -> Tuple[
    str, str, str, List[APIEndpoint], List[AuthRequirement], List[str]
]:
    """Parse OpenAPI 2.x / 3.x spec into endpoint list."""
    errors: List[str] = []
    endpoints: List[APIEndpoint] = []

    info = spec.get("info", {})
    title = str(info.get("title", ""))
    version = str(info.get("version", ""))

    # Base URL
    if "servers" in spec:
        servers = spec["servers"]
        base_url = servers[0].get("url", "") if servers else ""
    elif "host" in spec:
        scheme = spec.get("schemes", ["https"])[0]
        base_path = spec.get("basePath", "")
        base_url = f"{scheme}://{spec['host']}{base_path}"
    else:
        base_url = ""

    auth_requirements = _extract_auth_requirements(spec)

    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        errors.append("'paths' is not a mapping — no endpoints extracted")
        return title, version, base_url, endpoints, auth_requirements, errors

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in ("parameters", "summary", "description", "servers"):
                continue
            if not isinstance(operation, dict):
                continue

            # Parameters
            params: List[APIParameter] = []
            for p in operation.get("parameters", []) + path_item.get("parameters", []):
                if not isinstance(p, dict):
                    continue
                # Resolve $ref (best-effort only)
                if "$ref" in p:
                    continue
                params.append(APIParameter(
                    name=str(p.get("name", "")),
                    location=str(p.get("in", "query")),
                    required=bool(p.get("required", False)),
                    param_type=str(
                        p.get("schema", {}).get("type", "") or p.get("type", "string")
                    ),
                    description=str(p.get("description", "")),
                ))

            # Auth detection
            requires_auth = bool(
                operation.get("security") is not None
                or spec.get("security")
                or auth_requirements
            )

            safety, reason = classify_endpoint(method, path)

            endpoints.append(APIEndpoint(
                method=method.upper(),
                path=str(path),
                operation_id=str(operation.get("operationId", "")),
                summary=str(operation.get("summary", "")),
                tags=list(operation.get("tags", [])),
                parameters=params,
                requires_auth=requires_auth,
                safety_classification=safety,
                safety_reason=reason,
            ))

    return title, version, base_url, endpoints, auth_requirements, errors


def _parse_postman(collection: dict) -> Tuple[
    str, str, str, List[APIEndpoint], List[AuthRequirement], List[str]
]:
    """Parse a Postman collection v2.x into endpoint list."""
    errors: List[str] = []
    endpoints: List[APIEndpoint] = []

    info = collection.get("info", {})
    title = str(info.get("name", "Postman Collection"))
    version = "postman"
    base_url = ""

    def _process_item(item: dict) -> None:
        if "item" in item:
            for sub in item["item"]:
                _process_item(sub)
            return
        request = item.get("request", {})
        if not isinstance(request, dict):
            return
        method = str(request.get("method", "GET")).upper()
        url_raw = request.get("url", {})
        if isinstance(url_raw, str):
            path = "/" + "/".join(url_raw.split("/")[3:]) if "/" in url_raw else url_raw
        elif isinstance(url_raw, dict):
            parts = url_raw.get("path", [])
            path = "/" + "/".join(str(p) for p in parts) if parts else "/"
        else:
            path = "/"

        safety, reason = classify_endpoint(method, path)

        endpoints.append(APIEndpoint(
            method=method,
            path=path,
            operation_id=str(item.get("name", "")),
            summary=str(item.get("name", "")),
            safety_classification=safety,
            safety_reason=reason,
        ))

    for item in collection.get("item", []):
        _process_item(item)

    return title, version, base_url, endpoints, [], errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class APIContractImporter:
    """Parse an API contract file into an APIContractReport."""

    def analyze(self, project_id: str, spec_path: str) -> APIContractReport:
        """Parse *spec_path* and return a classified APIContractReport."""
        path = Path(spec_path)
        data, source_format, load_errors = _load_file(path)

        if data is None:
            report = APIContractReport(
                project_id=project_id,
                source_format=source_format,
                source_file=str(path),
                parse_errors=load_errors,
            )
            return report

        if source_format == "postman_collection":
            title, version, base_url, endpoints, auth_reqs, parse_errors = _parse_postman(data)
        else:
            title, version, base_url, endpoints, auth_reqs, parse_errors = _parse_openapi(
                data, source_format
            )

        safe_count = sum(1 for e in endpoints if e.safety_classification == "safe_readonly")
        approval_count = sum(1 for e in endpoints if e.safety_classification == "requires_approval")
        blocked_count = sum(1 for e in endpoints if e.safety_classification == "blocked_by_default")

        return APIContractReport(
            project_id=project_id,
            source_format=source_format,
            source_file=str(path),
            spec_title=title,
            spec_version=version,
            base_url=base_url,
            endpoints=endpoints,
            auth_requirements=auth_reqs,
            total_endpoints=len(endpoints),
            safe_readonly_count=safe_count,
            requires_approval_count=approval_count,
            blocked_count=blocked_count,
            parse_errors=load_errors + parse_errors,
            notes=[
                f"Parsed {len(endpoints)} endpoints from {source_format}",
                f"Safe: {safe_count}, Requires approval: {approval_count}, Blocked: {blocked_count}",
            ],
        )
