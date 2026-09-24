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
}


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

    for field_name, spec in properties.items():
        if spec.get("format") in {"password", "secret"} or spec.get("x-sensitive") is True:
            raise ChikletError(
                f"{source}: raw secret field {field_name!r} is not permitted; "
                "use a secret reference resolved by Foreman/Vault instead"
            )
        ui = spec.get("x-ui") or {}
        if not isinstance(ui, dict):
            raise ChikletError(f"{source}: {field_name}.x-ui must be an object")
        widget = ui.get("widget")
        if widget and widget not in SUPPORTED_WIDGETS:
            raise ChikletError(
                f"{source}: {field_name}.x-ui.widget {widget!r} is unsupported; "
                f"use one of {', '.join(sorted(SUPPORTED_WIDGETS))}"
            )
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


def build_form_layout(chiklet, values=None):
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
        current = values[name] if name in values else spec.get("default")
        field = {
            "name": name,
            "spec": spec,
            "title": spec.get("title") or name.replace("_", " ").title(),
            "description": spec.get("description"),
            "help": ui.get("help"),
            "placeholder": ui.get("placeholder", spec.get("placeholder", "")),
            "required": name in required,
            "readonly": spec.get("readOnly") is True,
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


def validate_form(chiklet, form):
    schema = chiklet["form_schema"]
    data = {}
    errors = []
    for prop, spec in schema.get("properties", {}).items():
        try:
            value = field_value_from_request(prop, spec, form)
            if value not in (None, "", []):
                data[prop] = value
            elif "default" in spec:
                data[prop] = spec["default"]
        except (TypeError, ValueError):
            errors.append(f"{spec.get('title', prop)} has an invalid value")

    for error in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda x: list(x.path)):
        errors.append(f"{'.'.join(map(str, error.path)) or 'Form'}: {error.message}")
    return data, errors
