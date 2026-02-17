# Contributing

## Rules

- **No secrets** in code, configs, or logs. Ever.
- **Receipts required** - every capability execution must produce a receipt + outcome event + policy decision.
- **Small PRs** - one concern per PR. Large PRs will be asked to split.
- **Tests required** for new features and bug fixes.
- **Default-deny** - new capabilities must declare allowed outbound domains explicitly.

## Workflow

1. Fork the repo
2. Create a branch: `git checkout -b feature/my-feature`
3. Make changes, run `make ci`
4. Open a PR using the template

## Commit Format

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `test`, `ci`, `chore`, `refactor`

## Local Development

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
bash scripts/dev.sh   # starts all 4 services
make demo             # run end-to-end demo
```

## Questions?

Use [GitHub Discussions](https://github.com/jeremylongshore/moat/discussions).
