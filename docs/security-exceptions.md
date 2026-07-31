# Security exceptions

## PYSEC-2026-2447 / CVE-2025-69872

- **Dependency:** `diskcache==5.6.3`, transitively required by `pysigma`
- **Status:** No fixed release is available as of 31 July 2026
- **Risk:** A local attacker who can write the cache directory can place a
  malicious pickle that executes when the application reads it
- **Sprinter exposure:** The Sigma endpoint accepts JSON only and does not
  expose filesystem paths or Python objects. The container is non-root,
  read-only, has no host mounts except its private data volumes, and gives Pi no
  tools. Untrusted users must not have local or volume write access.
- **Decision:** Temporarily ignore this advisory in `pip-audit`; do not ignore
  it in container or OS scanning
- **Owner:** Sprinter maintainers
- **Expiry:** Remove the exception immediately when `diskcache` or `pysigma`
  publishes a fixed compatible release, or disable Sigma conversion if the
  stated filesystem isolation cannot be maintained
- **Review cadence:** Every dependency update and at least monthly
