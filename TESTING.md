# Testing

Actual local commands run from this repository root on 2026-11-03:

```console
python --version
python -m unittest discover -s tests -v
```

CPython 3.11.15 on Windows 10 build 26300; test-only SQLite 3.53.1. Result: 19 tests passed, with no warnings. The CLI is invoked by basename with `cwd` set to the repository root and finite subprocess timeouts. Core cases import the module directly instead of spawning a CLI per oracle case.

The initial tests were written before the product file existed. The actual RED run reported 19 assertion failures for the missing scanner. After implementing the original scanner, the suite passed. Additional regression RED runs caught reserved CONIN$/CONOUT$ path handling and directly attached `:x(...)`/`@x(...)` suffixes; both were fixed and the complete suite returned GREEN. Builder transcripts are retained outside the publication tree in the batch's builder-evidence directory.

Coverage includes doubled quotes/backticks, bracket first-close, CR versus LF line comments, block comments, false parameter markers, Unicode character positions, ordinary identifiers containing `$`, repeated and mixed-prefix names sharing a Python key, mismatched containers/counts, missing and extra keys, explicit unsupported forms, malformed contexts, duplicate/nonfinite/surrogate JSON, input/depth/node/parameter/name limits, private outputs, reserved/remote/device spellings rejected before first file access, unchanged input bytes, regular-file checks and invalid UTF-8. Closed-pipe tests actually close the child's stdout read endpoint for both normal analysis and help and require exit 2 without traceback or shutdown exit 120.

Real SQLite oracle checks use only in-memory SELECT statements in tests. The product does not import the database module or prepare/execute SQL. These tests validate selected supported cases, not arbitrary SQL equivalence, race resistance or a universal driver guarantee.

`checks.json` contains four source-root smoke commands with expected exits 0, 1, 2 and 0, respectively. Fixture content is synthetic.
