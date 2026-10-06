# Capture execution contract implementation plan
> Use superpowers:executing-plans inline under standing authorization.
Goal: make prospective declarations checkable against execution and freeze declared inputs without silent omissions.
Spec: docs/superpowers/specs/2026-10-06-capture-execution-contract.md
Architecture: small pure contract module, capture wiring, isolated file snapshot module, tests and read-only inventory.
## Review focus
Strict type/duplicate JSON handling; validation before any subprocess; descriptor/path symlink race; partial manifest cannot qualify; installed inventory must not imply complete runtime closure.
## Tasks
- [x] TDD contract mismatch/refusal/actual supervisor limits. Add capture_contract.py and wire capture parser/main/worker. Expected initial missing module RED, then targeted GREEN.
- [x] TDD declared file and ldd refusal, IO and drift. Add declared_runtime_snapshot.py. Expected missing module RED then targeted GREEN. Do not launch simulations.
- [x] Read-only WSL inventory, upstream/license record; full regression, independent review, resolve Important with RED/GREEN, report/seal/draft PR. Expected no competing resources, truthful incomplete closure report.
