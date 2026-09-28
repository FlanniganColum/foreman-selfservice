import json
from pathlib import Path
from functools import lru_cache
from flask import current_app
from jsonschema import Draft202012Validator
from ..extensions import db
from ..models import Server


class ChikletError(ValueError):
    pass


SUPPORTED_WIDGETS = {
    "text",
    "textarea",
    "select",
    "multiselect",
    "toggle",
    "number",
    "date",
    "datetime-local",
    "password",
    "secret-textarea",
}


def sensitive_fields(chiklet):
    return {name for name, spec in chiklet["form_schema"].get("properties", {}).items()
            if spec.get("x-sensitive") is True}


def approval_mode(chiklet):
    return chiklet.get("approval", {}).get("mode", "full")


def bound_username(chiklet):
    binding = chiklet.get("identity_binding")
    if not binding:
        return {}
    from ..auth.services import authenticated_username
    username = authenticated_username(binding["providers"])
    return {binding["username_field"]: username} if username else None


@lru_cache(maxsize=256)
def _load_file_cached(path, mtime_ns):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _validate_definition(data, path)
    return data


def _validate_definition(data, source=""):
    required = {"id", "version", "name", "description", "icon", "allowed_server_groups", "form_schema", "foreman"}
    missing = sorted(required - set(data))
    if missing:
        raise ChikletError(f"{source}: missing keys: {', '.join(missing)}")

    allowed_groups = data.get("allowed_server_groups")
    if not isinstance(allowed_groups, list) or not allowed_groups or not all(isinstance(x, str) and x.strip() for x in allowed_groups):
        raise ChikletError(f"{source}: allowed_server_groups must be a non-empty list of group slugs or ['*']")
    if "*" in allowed_groups and allowed_groups != ["*"]:
        raise ChikletError(f"{source}: wildcard '*' must be the only entry in allowed_server_groups")

    icon = data.get("icon")
    if isinstance(icon, str):
        if not icon.strip():
            raise ChikletError(f"{source}: icon cannot be empty")
    elif isinstance(icon, dict):
        icon_type = icon.get("type")
        if icon_type == "image":
            src = icon.get("src")
            if not isinstance(src, str) or not src.strip():
                raise ChikletError(f"{source}: image icon requires a non-empty src")
            if not src.startswith("/"):
                path = Path(src)
                if path.is_absolute() or ".." in path.parts:
                    raise ChikletError(f"{source}: image icon src must be relative to chiklets/assets and cannot traverse directories")
                if path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
                    raise ChikletError(f"{source}: unsupported image icon extension {path.suffix!r}")
        elif icon_type == "text":
            value = icon.get("value")
            if not isinstance(value, str) or not value.strip():
                raise ChikletError(f"{source}: text icon requires a non-empty value")
        else:
            raise ChikletError(f"{source}: icon.type must be 'image' or 'text'")
    else:
        raise ChikletError(f"{source}: icon must be a string or an icon object")

    schema = data["form_schema"]
    Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object":
        raise ChikletError(f"{source}: form_schema.type must be 'object'")
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ChikletError(f"{source}: form_schema.properties must be an object")

    approval = data.get("approval", {"mode": "full"})
    if not isinstance(approval, dict) or set(approval) != {"mode"} or approval["mode"] not in {"none", "business", "full"}:
        raise ChikletError(f"{source}: approval.mode must be 'none', 'business', or 'full'")
    binding = data.get("identity_binding")
    if binding is not None:
        if (not isinstance(binding, dict) or set(binding) != {"username_field", "providers"}
                or not isinstance(binding.get("username_field"), str)
                or not isinstance(binding.get("providers"), list)
                or not binding["providers"] or not all(p in ("ldap", "entra") for p in binding["providers"])):
            raise ChikletError(f"{source}: identity_binding needs username_field and providers (ldap/entra)")
        field = binding["username_field"]
        spec = properties.get(field)
        if not isinstance(spec, dict) or spec.get("type") != "string" or spec.get("x-sensitive") or "default" in spec:
            raise ChikletError(f"{source}: identity-bound username field must be a string without a default or sensitive flag")

    for field_name, spec in properties.items():
        if spec.get("format") in {"password", "secret"} and spec.get("x-sensitive") is not True:
            raise ChikletError(f"{source}: {field_name!r} must set x-sensitive: true")
        if spec.get("x-sensitive") is True:
            if spec.get("type") != "string" or spec.get("readOnly") or "default" in spec or "enum" in spec:
                raise ChikletError(f"{source}: sensitive field {field_name!r} must be an editable string without default or enum")
        ui = spec.get("x-ui") or {}
        if not isinstance(ui, dict):
            raise ChikletError(f"{source}: {field_name}.x-ui must be an object")
        widget = ui.get("widget")
        if widget and widget not in SUPPORTED_WIDGETS:
            raise ChikletError(
                f"{source}: {field_name}.x-ui.widget {widget!r} is unsupported; "
                f"use one of {', '.join(sorted(SUPPORTED_WIDGETS))}"
            )
        if spec.get("x-sensitive") is True and widget not in (None, "password", "secret-textarea"):
            raise ChikletError(f"{source}: sensitive field {field_name!r} requires a password or secret-textarea widget")
        if spec.get("x-sensitive") is not True and widget in {"password", "secret-textarea"}:
            raise ChikletError(f"{source}: {field_name!r} must set x-sensitive: true")
        if "order" in ui and not isinstance(ui["order"], (int, float)):
            raise ChikletError(f"{source}: {field_name}.x-ui.order must be numeric")
        if ui.get("width", "full") not in {"full", "half"}:
            raise ChikletError(f"{source}: {field_name}.x-ui.width must be 'full' or 'half'")
        if "enum_labels" in ui and not isinstance(ui["enum_labels"], dict):
            raise ChikletError(f"{source}: {field_name}.x-ui.enum_labels must be an object")
        if spec.get("readOnly") is True and "default" not in spec:
            raise ChikletError(f"{source}: readOnly field {field_name!r} requires a default value")

    foreman = data["foreman"]
    if "job_template_id" not in foreman and "job_template_name" not in foreman:
        raise ChikletError(f"{source}: foreman job template is required")

    input_map = foreman.get("input_map", {})
    if not isinstance(input_map, dict):
        raise ChikletError(f"{source}: foreman.input_map must be an object")
    for foreman_name, source_name in input_map.items():
        if not isinstance(foreman_name, str) or not foreman_name.strip() or not isinstance(source_name, str) or not source_name.strip():
            raise ChikletError(f"{source}: foreman.input_map keys and values must be non-empty strings")
    unknown_sources = sorted({source_name for source_name in input_map.values() if source_name not in properties})
    if unknown_sources:
        raise ChikletError(
            f"{source}: foreman.input_map references fields not present in form_schema.properties: "
            f"{', '.join(unknown_sources)}"
        )
    if binding and binding["username_field"] not in input_map.values():
        raise ChikletError(f"{source}: identity-bound username field must be mapped to Foreman")
    unmapped_secrets = sensitive_fields(data) - set(input_map.values())
    if unmapped_secrets:
        raise ChikletError(f"{source}: sensitive fields must be mapped to Foreman: {', '.join(sorted(unmapped_secrets))}")


def list_chiklets():
    base = Path(current_app.config["CHIKLET_DIRECTORY"])
    return [_load_file_cached(str(p), p.stat().st_mtime_ns) for p in sorted(base.glob("*.json"))]


def get_chiklet(chiklet_id):
    return next((x for x in list_chiklets() if x["id"] == chiklet_id), None)


def chiklet_allows_group(chiklet, group_slug):
    allowed = set(chiklet.get("allowed_server_groups", []))
    return "*" in allowed or group_slug in allowed


def can_user_access_chiklet(user, chiklet):
    if user.is_global_admin():
        return True
    user_groups = {g.slug for g in user.server_groups if g.enabled}
    allowed = set(chiklet.get("allowed_server_groups", []))
    if "*" in allowed:
        return bool(user_groups)
    return bool(allowed & user_groups)


def can_user_target_server(user, chiklet, server):
    if not server or not server.enabled or not server.group or not server.group.enabled:
        return False
    if not chiklet_allows_group(chiklet, server.group.slug):
        return False
    if user.is_global_admin():
        return True
    return any(g.enabled and g.id == server.group_id for g in user.server_groups)


def authorised_servers(user, chiklet):
    servers = db.session.scalars(db.select(Server).where(Server.enabled.is_(True)).order_by(Server.name)).all()
    return [server for server in servers if can_user_target_server(user, chiklet, server)]


def _infer_widget(spec):
    ui = spec.get("x-ui") or {}
    if ui.get("widget"):
        return ui["widget"]
    if spec.get("x-sensitive") is True:
        return "secret-textarea" if spec.get("format") in {"multiline", "textarea"} else "password"
    if spec.get("enum") is not None:
        return "select"
    if spec.get("type") == "boolean":
        return "toggle"
    if spec.get("type") == "array" and (spec.get("items") or {}).get("enum") is not None:
        return "multiselect"
    if spec.get("type") in {"integer", "number"}:
        return "number"
    if spec.get("format") == "date":
        return "date"
    if spec.get("format") == "date-time":
        return "datetime-local"
    if spec.get("format") in {"multiline", "textarea"}:
        return "textarea"
    return "text"


def _enum_options(spec):
    values = spec.get("enum")
    if values is None and spec.get("type") == "array":
        values = (spec.get("items") or {}).get("enum")
    values = values or []
    labels = (spec.get("x-ui") or {}).get("enum_labels") or {}
    return [{"value": value, "label": labels.get(str(value), str(value))} for value in values]


def build_form_layout(chiklet, values=None, *, bound_values=None):
    """Convert a Chiklet JSON Schema into presentation metadata for the GUI.

    JSON Schema remains authoritative for validation; x-ui only controls presentation.
    Defaults are editable unless readOnly=true.
    """
    schema = chiklet["form_schema"]
    required = set(schema.get("required", []))
    values = values or {}
    groups = {}

    for index, (name, spec) in enumerate(schema.get("properties", {}).items()):
        ui = spec.get("x-ui") or {}
        group_name = ui.get("group") or "Configuration"
        current = (bound_values[name] if bound_values and name in bound_values else
                   None if spec.get("x-sensitive") is True else (values[name] if name in values else spec.get("default")))
        field = {
            "name": name,
            "spec": spec,
            "title": spec.get("title") or name.replace("_", " ").title(),
            "description": spec.get("description"),
            "help": ui.get("help"),
            "placeholder": ui.get("placeholder", spec.get("placeholder", "")),
            "required": name in required,
            "readonly": spec.get("readOnly") is True or (bound_values is not None and name in bound_values),
            "widget": _infer_widget(spec),
            "options": _enum_options(spec),
            "value": current,
            "order": ui.get("order", index),
            "width": ui.get("width", "full"),
        }
        groups.setdefault(group_name, []).append(field)

    result = []
    for group_index, (group_name, fields) in enumerate(groups.items()):
        fields.sort(key=lambda field: (field["order"], field["title"]))
        result.append({"name": group_name, "order": min((f["order"] for f in fields), default=group_index), "fields": fields})
    result.sort(key=lambda group: group["order"])
    return result


def field_value_from_request(prop, spec, form):
    # Read-only fields are configuration owned by the Chiklet. Never trust a
    # browser-supplied value for them, even if a user tampers with the HTML.
    if spec.get("readOnly") is True:
        return spec.get("default")

    raw = form.get(f"field__{prop}")
    t = spec.get("type")
    if t == "boolean":
        return raw in {"1", "true", "on", "yes"}
    if t == "integer":
        return int(raw) if raw not in (None, "") else None
    if t == "number":
        return float(raw) if raw not in (None, "") else None
    if t == "array":
        return form.getlist(f"field__{prop}")
    return raw


def validate_form(chiklet, form, *, bound_values=None, with_fields=False):
    schema = chiklet["form_schema"]
    data = {}
    errors = []
    field_errors = {}
    for prop, spec in schema.get("properties", {}).items():
        try:
            value = bound_values[prop] if bound_values and prop in bound_values else field_value_from_request(prop, spec, form)
            if value not in (None, "", []):
                data[prop] = value
            elif "default" in spec:
                data[prop] = spec["default"]
        except (TypeError, ValueError):
            message = f"{spec.get('title', prop)} has an invalid value"
            errors.append(message)
            field_errors.setdefault(prop, message)

    for error in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda x: list(x.path)):
        field = next(iter(error.path), None)
        if field is None and error.validator == "required" and isinstance(error.instance, dict):
            field = next((name for name in error.validator_value if name not in error.instance), None)
        if field in sensitive_fields(chiklet):
            message = f"{schema['properties'][field].get('title', field)}: enter a valid value"
        elif error.validator == "required" and field in schema.get("properties", {}):
            message = f"{schema['properties'][field].get('title', field)} is required"
        elif not error.path:
            message = "Form: check the submitted values"
        else:
            message = f"{'.'.join(map(str, error.path)) or 'Form'}: {error.message}"
        errors.append(message)
        if field in schema.get("properties", {}):
            field_errors.setdefault(field, message)
    return (data, errors, field_errors) if with_fields else (data, errors)
