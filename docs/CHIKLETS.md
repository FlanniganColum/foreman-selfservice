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
| `x-sensitive: true` string | password control, or secret textarea with `x-ui.widget: secret-textarea` |

Defaults are initial values, not locks. A user may change a default unless the field has `readOnly: true`.

## `x-ui` presentation hints

`x-ui` affects presentation only. JSON Schema remains authoritative for validation.

Supported keys:

- `widget`: `text`, `textarea`, `select`, `multiselect`, `toggle`, `number`, `date`, `datetime-local`, `password`, or `secret-textarea`.
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

Sensitive string fields may be entered in the portal with `x-sensitive: true`. The portal writes their values to HashiCorp Vault KV v2 at `<VAULT_KV_MOUNT>/<VAULT_KV_PREFIX>/<request UUID>` and retains only `vault-kv2://<mount>/<prefix>/<request UUID>#<field>` references in the request history and Foreman inputs. A sensitive field must be editable, have no default or enum, and be listed in `foreman.input_map`. The portal does not read secrets back. The Foreman job template must resolve references with a **separate read-only Vault identity** and use Ansible `no_log: true` on every task that handles secret material. Never print resolved values, enable HTTP request-body logging, or include them in justifications and other ordinary text fields. Foreman output is displayed in the portal, so `no_log` on the job is essential.

Example field and mapping:

```json
"ssh_private_key": {"type": "string", "title": "SSH private key", "x-sensitive": true,
                    "x-ui": {"widget": "secret-textarea"}}
```

```json
"input_map": {"ssh_private_key_ref": "ssh_private_key"}
```

### Foreman Ansible job output

Use an Ansible provider job template for Chiklets that resolve Vault references. Keep `no_log: true` on the lookup and **every** task that consumes the resolved value, including failure handlers; leave ordinary progress and status tasks visible. `no_log` hides a protected task's result (including command `stdout` and `stderr`) in Foreman, but does not remove the result from Ansible's in-memory registered variables or suppress output produced outside Ansible. Do not put a secret or its reference into a task name, job description, `debug` message, shell command line, or unprotected `register`/failure handler. Disable Ansible debug mode and avoid diff output for secret-bearing tasks.

For example, with a Foreman input named `ssh_private_key_ref`, pass the reference to the playbook as `ssh_private_key_ref` and adapt the install task to your intended destination:

```yaml
tasks:
  - name: Validate the private key reference
    ansible.builtin.assert:
      that:
        - ssh_private_key_ref is match('^vault-kv2://portal/requests/[0-9a-fA-F-]{36}#ssh_private_key$')
      fail_msg: Invalid secret reference
    no_log: true

  - name: Resolve the private key from Vault
    ansible.builtin.set_fact:
      private_key: >-
        {{ lookup('community.hashi_vault.vault_kv2_get',
                  ssh_private_key_ref | regex_replace('^vault-kv2://portal/', '') | regex_replace('#.*$', ''),
                  engine_mount_point='portal').secret['ssh_private_key'] }}
    no_log: true

  - name: Install the private key with restricted permissions
    ansible.builtin.copy:
      content: "{{ private_key }}"
      dest: /etc/myapp/client.key
      owner: root
      group: root
      mode: '0600'
    no_log: true
    diff: false

  - name: Report completion
    ansible.builtin.debug:
      msg: Private key installed successfully
```

The lookup runs on the Ansible controller; configure its read-only Vault identity and trusted Vault CA there, and install `community.hashi_vault` and its `hvac` dependency. Do not pass the Vault read token through a Chiklet input. If the protected step fails, Foreman still records failure status but its detailed result is intentionally hidden. Emit only a fixed, sanitized failure message from a separate task if the operator needs more context. Review other application and remote-host logs independently: Ansible `no_log` cannot redact them.

Set `VAULT_ADDR` to an HTTPS Vault endpoint and `VAULT_TOKEN_FILE` to a mounted file containing the portal token (or `VAULT_TOKEN` for development). Set `VAULT_CA_BUNDLE` for a private CA; `VAULT_KV_MOUNT` and `VAULT_KV_PREFIX` select the KV v2 location. Grant the portal token `create` and `update` on `<mount>/data/<prefix>/*`; grant the Foreman job identity `read` on that path. Keep the Foreman read credential outside the portal and use short-lived identities where possible. Configure retention/deletion in Vault for rejected, completed and orphaned submissions. A failed database commit after a successful Vault write can leave an orphaned secret at the request UUID path. Run the deployment behind HTTPS, redact request bodies at the reverse proxy, WAF, APM and error reporter. An SSH **public** key need not be secret, but a private key must use this path; prefer users supplying public keys when possible.

Vault KV v2 response errors are deliberately reduced to generic messages. The raw secret is never repopulated in a form after validation failure. Existing Chiklets without sensitive fields need no Vault configuration.

`readOnly` is enforced server-side. Editing browser HTML cannot override the value defined by the Chiklet.
