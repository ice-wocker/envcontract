# EnvContract

**A small, dependency-free environment-variable contract auditor.** Find when code expects keys your `.env.example` forgot—or when the template carries stale keys. Local-first, CI-friendly, and deliberately careful with secrets.

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB)](#) [![Dependencies](https://img.shields.io/badge/Dependencies-zero-237a57)](#) [![License](https://img.shields.io/badge/License-MIT-343434)](LICENSE)

**EnvContract never auto-opens real `.env` files.** From a selected example file it extracts key names and ignores assignment values; reports contain names and source locations only, never matching source lines.

[中文说明](#中文说明)

## The gap it closes

Environment configuration drifts quietly. A new `process.env.BILLING_KEY` lands in code, `.env.example` stays untouched, and deploys fail later—often in a different environment. EnvContract statically maps common environment lookups and compares that map with an explicit example contract.

```text
$ python3 envcontract.py . --check
EnvContract · environment contract audit
────────────────────────────────────────────────
Root: /work/storefront
Example: .env.example
Source/config files scanned: 42
Variables referenced: 9 · declared: 8

MISSING FROM EXAMPLE
  + BILLING_KEY                 src/billing.ts:18

Run `envcontract --write-example` to generate a blank template.
```

## Quick start

```bash
# No install, no dependencies
python3 envcontract.py .

# Make config drift fail CI
python3 envcontract.py . --check

# Point at a nonstandard example file
python3 envcontract.py . --example deploy/.env.sample --format json

# Create a safe, blank template from discovered names
python3 envcontract.py . --write-example .env.example
```

`--write-example` refuses to overwrite by default. Use `--force` only when replacing the template is intentional. Generated values are always blank.

## What it detects

- Python: `os.getenv`, `os.environ.get`, `os.environ["KEY"]`
- JavaScript / TypeScript: `process.env.KEY`, `process.env["KEY"]`, `import.meta.env.KEY`
- Go, Java, Rust, PHP, Ruby: common standard-library environment lookups
- Shell, Docker, and common config files: `$KEY` and `${KEY}` interpolation
- Missing, unused, and duplicate keys in `.env.example`, `.env.sample`, `.env.template`, or `.env.defaults`
- JSON output for CI annotations, scripts, and dashboards

The analyzer is intentionally static and conservative—not a language compiler. Dynamic key construction such as `os.getenv(prefix + name)` cannot be inferred. Review findings before treating them as a complete inventory.

## Safety model

- Never auto-opens `.env` or `.env.local` files.
- Extracts keys from the selected example file; assignment values are ignored and never included in reports.
- Does not send data over the network or invoke a shell.
- Prints variable names and file/line locations, never matching source lines.
- Skips common generated/vendor directories and files over 1 MiB.

The scanner is not a secret detector; use a dedicated secret scanner for that job. Keep real credentials out of source and templates.

## CI

```yaml
- name: Check environment contract
  run: python3 envcontract.py . --check
```

A non-zero status is returned only when `--check` is supplied and the report contains missing, unused, or duplicate declarations. `--format json` produces machine-readable results; findings include references as `{path, line}` objects.

## Supported scope

The tool targets Python 3.8+ and the standard library only. It scans common source/config extensions and excludes `.git`, package caches, virtual environments, and build output. See `SOURCE_SUFFIXES` and `IGNORED_DIRS` in `envcontract.py` to tune these choices for a specialized repository.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## 中文说明

EnvContract 是一个零依赖的环境变量契约检查器：从代码和配置中提取常见环境变量引用，与 `.env.example` 等模板对比，报告缺失项、未使用项和重复声明，适合本地检查与 CI。

它默认**不会打开真实的 `.env` 文件**；从指定模板中提取变量名，忽略并且不输出等号右侧的值，也不会把源码行打印到终端。它不联网、不调用 Shell，也不是 Secret Scanner。静态分析无法推断动态拼接的变量名，结果应作为检查线索，而非语言级完整证明。

```bash
python3 envcontract.py . --check
python3 envcontract.py . --example deploy/.env.sample --format json
python3 envcontract.py . --write-example .env.example
```

## License

MIT. See [LICENSE](LICENSE).
