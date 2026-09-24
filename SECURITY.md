# Security model

Three authentication providers converge on one internal user model: Microsoft Entra ID, LDAP/AD, and local Argon2 credentials. Auto-provisioned external identities receive no server entitlement by default.

Authorization is enforced server-side. Application roles (`user`, `approver`, `admin`, `auditor`, `global_admin`) are separate from resource entitlements (`ServerGroup`). A Chiklet also restricts which server-group slugs it may target, and both checks must pass.

All requests require approval. The request's target, Chiklet configuration and form values are snapshotted before approval. Requesters cannot approve their own requests.

Foreman credentials are backend-only. Use a dedicated least-privilege service identity and keep TLS verification enabled.

Do not commit `.env`, private keys, LDAP bind passwords, Entra secrets or Foreman credentials. For high-assurance deployments, move secrets to your enterprise secrets platform and ship audit/application logs to an immutable SIEM.

Production acceptance should include vulnerability scanning, penetration testing, restore/DR testing, Foreman-version integration testing, and your organisation's security/change-management review.
