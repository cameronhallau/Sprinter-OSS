# Security policy

## Supported versions

Only the latest tagged Sprinter release receives security fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature for this repository.
Include affected versions, reproduction steps, impact, and any suggested
mitigation. Do not include credentials, customer data, or active exploit
details in a public issue.

Maintainers should acknowledge a report within three business days, provide an
initial assessment within seven business days, and coordinate disclosure after
a fixed release is available.

## Deployment responsibility

Sprinter processes security evidence and model prompts. Operators must apply
least privilege to every backend credential, terminate public TLS at a trusted
reverse proxy, restrict network egress, protect the SQLite and Pi credential
volumes, and review the threat model before deployment.
