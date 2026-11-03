# Research and scope

Primary sources retrieved 2026-11-03. This original implementation is a bounded handoff checker, not an SQLite tokenizer clone or SQL parser. No upstream implementation was copied.

## Source catalog and established facts

1. [SQLite SQL expressions: parameters](https://www.sqlite.org/lang_expr.html#parameters): documents `?NNN`, `?`, `:`, `@`, `$`, numbering rules, connection-dependent limits and the Tcl-style dollar name extension. This establishes that a plain count of question marks is insufficient for unrestricted SQLite SQL.
2. [Python 3.11 sqlite3: placeholder binding](https://docs.python.org/3.11/library/sqlite3.html#how-to-use-placeholders-to-bind-values-in-sql-queries): qmark sequences must have matching length; named mappings must contain required keys, while extra items are ignored. The tool deliberately chooses stricter extra-key coverage. JSON nested values are outside any guarantee of successful SQLite adaptation.
3. [SQLite draft tokenizer requirements](https://www.sqlite.org/draft/tokenreq.html): describes longest-token processing, quotes, bracket first-close behavior, comments, Unicode identifier classes and interior `$` in identifiers. This page is explicitly a draft, so it is supporting lexical evidence rather than a complete/current normative specification. Its block-comment description permits end-of-input; the tool's narrower policy requires `*/`.

## Observed local evidence

The test suite uses the real stdlib SQLite driver only inside tests, with in-memory `SELECT` statements. It confirms quoted/comment false positives, repeated names and the mapping behavior `SELECT :x, @x` with `{"x":8}` producing two eights. It also confirms extra mapping items are ignored by that driver while the tool reports them. These observations are specific to CPython 3.11.15 / SQLite 3.53.1 on the verified local environment; they are not evidence for all drivers, schemas or versions.

## Inference and chosen policy

Separating occurrences, unique prefixed slots and prefixless mapping names avoids conflating SQLite's parameter identity with Python's mapping lookup. The scanner recognizes dollar-containing ordinary identifiers as whole tokens to avoid a false parameter in `foo$bar`. Ambiguous parameter extensions, multiple marker adjacency and nested brackets are refused instead of partially counted.

Strict JSON, fixed resource caps, read-only operation and value-free reports make this useful for reviewing a handoff without executing submitted SQL. They do not establish SQL validity, injection resistance or storage locality. ASCII names, numbered-placeholder refusal, stricter extra-key checking and closed-block-comment requirements are product policies rather than limits of SQLite itself. File-path refusal rules are conservative spelling policies, including CLOCK$ and NUL-space variants; no platform experiment proving each reserved spelling is asserted.

## Alternative

Using an actual SQLite driver to prepare/execute in a controlled test environment checks much more of SQLite's grammar and binding rules. It may require schema/context, applies actual driver/value limits, and can execute SQL. This tool trades that breadth for a transparent static subset with no database access. Other drivers and adapter configurations require their own integration tests.

## 中文边界

SQLite 文档与 Python 驱动文档用于确定参数规则；草案分词文档只作词法依据。实测仅证明当前本地版本的少量内存 SELECT 行为。严格多余键检查、ASCII 名称、资源限制和路径拒绝均为本工具策略，不能推导出通用驱动兼容、SQL 安全或底层存储一定在本机。
