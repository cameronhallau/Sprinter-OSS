# Release policy

Sprinter uses semantic versions. Releases are cut from protected tags only
after tests, type checking, linting, secret scanning, dependency audits,
CodeQL, container scanning, and the environment-gated staging acceptance run.

Each release publishes:

- Multi-architecture OCI image by immutable digest
- SHA-256 checksums
- SPDX and CycloneDX SBOMs
- Vulnerability scan results
- Keyless Cosign signature
- GitHub build provenance attestation

Dependency updates, including Pi, arrive through reviewed pull requests.
Pi upgrades must pass version, JSONL framing, provider authentication, timeout,
schema validation, and no-fallback tests before the pin changes.

The maintainers may withdraw a release with a critical security defect. Only
the latest release is supported.
