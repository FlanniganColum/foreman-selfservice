# Chiklet form schema

Chiklet JSON files are the source of truth for the Self-Service application form. The portal reads each Chiklet dynamically, renders the form controls from `form_schema`, validates the submitted values against the same JSON Schema, stores the approved values in the immutable request snapshot, and maps those values into Foreman job-template inputs using `foreman.input_map`.

## Example

```json
{
  "id": "install-mssql-odbc-driver",
  "version": "1.1.0",
  "name": "Install MSSQL ODBC Driver",
  "description": "Install and configure the Microsoft SQL Server ODBC driver.",
  "category": "Database",
  "icon": {"type": "image", "src": "mssql.svg", "alt": "Microsoft SQL Server"},
  "allowed_server_groups": ["*"],
  "form_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "mssql_odbc_package": {
        "type": "string",
        "title": "ODBC Driver Package",
        "enum": ["msodbcsql17", "msodbcsql18"],
        "default": "msodbcsql18",
        "description": "Driver package to install.",
        "x-ui": {
          "group": "Microsoft packages",
          "order": 10,
          "width": "half"
        }
      },
      "mssql_tools_package": {
        "type": "string",
        "title": "Tools Package",
        "enum": ["mssql-tools", "mssql-tools18"],
        "default": "mssql-tools18",
        "x-ui": {
          "group": "Microsoft packages",
          "order": 20,
          "width": "half"
        }
      },
      "mssql_package_state": {
        "type": "string",
        "title": "Package State",
        "enum": ["present", "latest"],
        "default": "present",
        "x-ui": {
          "group": "Installation",
          "enum_labels": {
            "present": "Installed",
            "latest": "Latest available"
          }
        }
      },
      "restart_service": {
        "type": "boolean",
        "title": "Restart service",
        "default": true,
        "x-ui": {"group": "Installation"}
      },
      "retry_count": {
        "type": "integer",
        "title": "Retry count",
        "default": 3,
        "minimum": 0,
        "maximum": 10,
        "x-ui": {"group": "Advanced", "width": "half"}
      },
      "operator_notes": {
        "type": "string",
        "title": "Operator notes",
        "default": "",
        "x-ui": {"group": "Advanced", "widget": "textarea", "rows": 5}
      },
      "approved_repository": {
        "type": "string",
        "title": "Repository",
        "default": "microsoft-approved",
        "readOnly": true,
        "x-ui": {"group": "Policy"}
      }
    },
    "required": ["mssql_odbc_package", "mssql_tools_package", "mssql_package_state"],
    "additionalProperties": false
  },
  "foreman": {
    "job_template_name": "SelfService - Install MSSQL ODBC Driver",
    "input_map": {
      "mssql_odbc_package": "mssql_odbc_package",
      "mssql_tools_package": "mssql_tools_package",
      "mssql_package_state": "mssql_package_state",
      "restart_service": "restart_service",
      "retry_count": "retry_count",
      "operator_notes": "operator_notes",
      "approved_repository": "approved_repository"
    }
  }
}
```

## Rendering rules

The portal infers controls from JSON Schema:

| Schema | GUI control |
| --- | --- |
| `type: string` | text input |
| `enum: [...]` | dropdown |
| `type: boolean` | checkbox/toggle |
| `type: integer` / `number` | numeric input |
| `type: array` with `items.enum` | multi-select |
| `format: date` | date picker |
| `format: date-time` | date/time picker |
| `format: multiline` or `format: textarea` | textarea |
| `readOnly: true` | displayed as fixed configuration |

Defaults are initial values, not locks. A user may change a default unless the field has `readOnly: true`.

## `x-ui` presentation hints

`x-ui` affects presentation only. JSON Schema remains authoritative for validation.

Supported keys:

- `widget`: `text`, `textarea`, `select`, `multiselect`, `toggle`, `number`, `date`, or `datetime-local`.
- `group`: section heading in the form.
- `order`: numeric field ordering within a section.
- `width`: `full` or `half`.
- `placeholder`: input placeholder.
- `help`: additional help text.
- `rows`: textarea row count.
- `enum_labels`: display labels for enum values while preserving the underlying value sent to Foreman.

## Foreman input mapping

The left side is the Foreman job-template input name. The right side is the Chiklet form field name.

```json
"input_map": {
  "foreman_input_name": "chiklet_form_field"
}
```

Every `input_map` source must exist in `form_schema.properties`. Invalid Chiklet definitions are rejected when loaded rather than allowing an unmapped or hidden value to reach Foreman.

## Security

Raw passwords and secret fields are intentionally prohibited from Chiklet forms because submitted values become part of the immutable request/audit history. Pass secret references and resolve the actual secret in Foreman, Ansible Vault, or the organisation's secret-management platform.

`readOnly` is enforced server-side. Editing browser HTML cannot override the value defined by the Chiklet.
