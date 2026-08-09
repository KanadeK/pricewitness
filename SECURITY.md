# Security policy

## Supported versions

Security fixes are provided for the latest tagged release.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository. Do not attach real receipts, ledgers, loyalty identifiers, addresses, or unredacted exports to a public issue.

Include a minimal synthetic reproducer, affected version, operating system, and expected/actual behavior. Maintainers will acknowledge a valid report within seven days when possible.

## Threat model

Receipt text, alias JSON, SQLite files, and imported filenames are untrusted. The project defends against:

- executable spreadsheet cells in CSV;
- markup/script injection in HTML reports;
- path disclosure through persisted absolute source paths;
- duplicate evidence insertion;
- guessed product identities from tied rules;
- unbounded input size and line length;
- configurable regular-expression denial of service;
- SQL injection through parameterized statements.

PriceWitness does not encrypt files at rest, sanitize original receipt files, authenticate local users, or protect a compromised operating system. Use encrypted storage and normal OS access controls for real household data.
