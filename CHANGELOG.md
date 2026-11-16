# Changelog

## 1.1.0 — 2026-11-16

- Added repeatable `--ignore GLOB` filters and a root `.envcontractignore` file for excluding inline fixtures, generated code, or shell-local false positives.
- Added an ignore-pattern regression test; the repository's own CI now runs `--check` as a clean-contract smoke test.
- Clarified that this is static pattern matching, not a compiler or secret scanner.

## 1.0.0 — 2026-11-16

- Initial release: cross-language environment reference scan, example-file comparison, blank template generation, text/JSON reports, and CI-friendly `--check`.
