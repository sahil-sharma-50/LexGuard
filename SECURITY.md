# Security Policy

Lexguard handles brokerage credentials, market data, operator controls, and
potentially sensitive account evidence. Treat the repository as a public
project unless a file is explicitly kept local and ignored.

## Reporting a vulnerability

Please do not open a public issue for credentials, authentication flaws,
private account data, or a bypass of the paper-only and fail-closed controls.
Use a private GitHub Security Advisory for the repository, or contact the
repository owner through a private channel.

Include enough detail to reproduce the issue without including live secrets.
If a credential may have been exposed, rotate it immediately and then report
the affected file, commit, or environment.

## Local secrets and private artifacts

- Store local credentials in .env, which is ignored by Git.
- Keep operator tokens long, random, and outside source control.
- Do not put secrets in NEXT_PUBLIC_* variables because they are exposed to
  browser clients.
- Treat account IDs, order exports, and paper-forward evidence as sensitive
  until they have been redacted for publication.
- Review the staged diff before every commit.

## Safety boundary

The application is intended for Alpaca paper trading only. Do not change the
paper endpoint checks, bypass preflight, or use live brokerage credentials in
development or CI.
