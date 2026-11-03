# sqlite-bind-shape

[![tests](https://github.com/maomao-1937/sqlite-bind-shape/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao-1937/sqlite-bind-shape/actions/workflows/tests.yml)

Check whether a JSON binding container covers the placeholders in a local SQL file, without opening a database. Useful for reviewing SQL/parameter handoffs before a driver call. Python 3.11+ standard library only.

## Run from source

Download this repository's source and open a terminal in its root. No package installation, API key, configuration file, environment variable, external command or dependency is needed.

```console
python sqlite_bind_shape.py examples/clean.sql examples/clean.json
python sqlite_bind_shape.py examples/clean.sql examples/missing.json
python sqlite_bind_shape.py --help
python -m unittest discover -s tests -v
```

Exactly two positional arguments are local filenames: SQLFILE and BINDINGSJSON. The tool reads files only and writes its report to stdout. UTF-8 is required; an optional UTF-8 BOM at the start of either file is removed. Relative paths resolve against the current working directory. Standard input and URI inputs are unsupported.

## Result

Exit 0 means coverage is clean under this subset; 1 means a container/count/missing/extra finding; 2 means invalid, unsupported, refused, operational or output error. A closed stdout pipe, including `--help`, exits 2 without a traceback. Successful analysis emits one JSON object, for example:

```json
{"code":"CLEAN","occurrences":4,"unique_prefixed_slots":3,"distinct_binding_names":2,"binding_items":2,"missing_names":0,"extra_names":0,"findings":[],"parameters":[{"ordinal":1,"position":8,"prefix":":"},{"ordinal":2,"position":17,"prefix":":"},{"ordinal":3,"position":26,"prefix":"@"},{"ordinal":4,"position":35,"prefix":"$"}]}
```

`ordinal` is a 1-based occurrence number, and `position` is a 1-based Unicode character index into the decoded SQL, including whitespace/comments; it is not a byte offset, line/column or binding slot number. Only fixed codes, counts, positions and marker prefixes appear. SQL text, placeholder names, JSON keys/values and filenames are never included in tool diagnostics. Counts and positions still reveal structural information.

For `:x, :x, @x`, there are 3 occurrences, 2 distinct prefixed SQLite slots (`:x`, `@x`) and 1 prefixless mapping name (`x`). A Python mapping supplies both slots using key `x`. `unique_prefixed_slots` counts anonymous occurrences when the mode is anonymous; `distinct_binding_names` is then 0. These are lexical counts across the whole file, not per prepared statement. Multiple statements are not parsed or separately validated.

## Supported profile

- Anonymous `?` requires a JSON array with exactly one element per occurrence.
- Named `:name`, `@name`, `$name` require a JSON object with prefixless keys; names match ASCII `[A-Za-z_][A-Za-z0-9_]*`, case sensitively. Repetitions reuse the prefixed slot.
- Missing names and extra mapping keys are findings (exit 1). Extras are a deliberately strict coverage policy: Python's SQLite driver ignores extra mapping items.
- With no parameters, only empty `[]` or `{}` is clean. Scalar top-level JSON is invalid (exit 2). A wrong array/object binding mode is a finding (exit 1).
- Single-quoted strings and double-quoted/backtick identifiers support doubled closing quotes. Bracket identifiers end at their first `]`; nested `[` is conservatively refused. `--` comments end at LF/end, not CR; block comments end at the first `*/` without nesting.
- Dollar characters inside ordinary identifiers, such as `foo$bar`, are not parameters. Other SQL tokens and grammar are not validated.

The tool refuses numbered `?NNN` (slot reuse/gaps), mixed anonymous/named forms, non-ASCII parameter spellings, digit-start names, bare or adjacent/ambiguous markers, `::` extensions and directly attached parenthesized name suffixes for every named prefix. It refuses unterminated quoted/comment contexts and SQL NUL. Even where SQLite itself accepts a form (such as an unterminated block comment), this narrow profile can refuse it.

JSON rejects duplicate keys at any depth, nonfinite constants/results (including overflowing float exponents), malformed text and unpaired surrogates in keys or values. Nested JSON values are accepted for shape analysis; this does **not** certify that those values can be bound by `sqlite3`, fit SQLite integers, or satisfy SQL types. Python's integer-conversion safety limit can additionally refuse very long integer tokens.

## Bounds and local-file policy

Each input is capped at 2,097,152 bytes, including a BOM when read from a file. JSON nesting is at most 64 containers, with at most 100,000 nodes (including object keys, values and containers). At most 10,000 parameter occurrences and 256 ASCII characters per named parameter are supported. Limits are fixed in the source and exceedance exits 2. These are work bounds, not a memory/CPU isolation guarantee.

Both filenames undergo lexical checks before either is statted or opened: URI/scheme/alternate-stream colon spellings are refused, except an absolute Windows drive prefix (`C:\...` or `C:/...`). UNC spellings, including mixed `/\` and `\/`, and Windows device prefixes are refused. Control characters and reserved components are refused case insensitively, including extensions: CON, PRN, AUX, NUL, CLOCK$, CONIN$, CONOUT$, COM1–9/LPT1–9 (also superscript 1/2/3). Reserved stems are checked after stripping trailing spaces/dots, so `NUL .sql` is conservatively refused. CLOCK$ and NUL-space rules describe this chosen profile, not a claim about every OS's device behavior.

Only regular files are read, checked before and after opening, with a bounded read. This is a spelling/file-type policy: symlinks, junctions, mount points, mapped drives or backing storage may still resolve elsewhere or to remote storage; there is no containment or remote-backing guarantee. A changing file can change between checks; the tool offers no atomic two-input snapshot. It performs no database, network, subprocess or file-write operation.

This is not SQL syntax, SQL injection, security, schema, transaction or universal-driver validation. For example `x?` can be counted although the SQL may be invalid. A clean report is only placeholder coverage under the documented lexical subset. Use a real driver in a controlled environment to validate an actual statement and values.

## 中文说明

本工具只读本地 SQL 文件和 JSON 绑定文件，静态检查占位符与绑定容器是否匹配，不连接数据库。直接在源码根目录执行上面的命令即可；需要 Python 3.11 或更新版本，无第三方依赖、环境变量或密钥。

匿名 `?` 对应等长 JSON 数组；`:name`、`@name`、`$name` 对应不含前缀的 JSON 对象键。相同前缀和名称重复出现共用一个 SQLite 槽位，不同前缀的同名参数占不同槽位，但 Python 映射使用同一个去前缀键。报告分别给出出现次数、带前缀槽位数和去前缀名称数。

退出码 0 表示本工具支持范围内的覆盖匹配；1 表示缺失、多余、数量或容器不符；2 表示无效、不支持、路径拒绝、读写输出异常等。多余对象键属于本工具的严格策略，Python sqlite3 本身会忽略多余键。报告不输出 SQL、参数名、值和路径；位置按解码后 Unicode 字符从 1 开始计数。

拒绝 `?NNN`、混用匿名和命名参数、非 ASCII 参数名、Tcl 扩展、歧义相邻标记和未闭合上下文。文件各限 2 MiB，JSON 深度 64、节点 100000，占位符 10000、参数名长度 256。只接受常规文件；路径规则不能证明符号链接、挂载点或映射盘背后的存储一定在本机。JSON 值通过检查不代表可被驱动绑定；结果也不证明 SQL 语法、安全性或实际执行成功。

## Verification and sources

Locally verified on Windows 10 build 26300, CPython 3.11.15, test-only SQLite 3.53.1. No hosted CI result is claimed here. See [TESTING.md](TESTING.md) for commands and [RESEARCH.md](RESEARCH.md) for primary sources, observed behavior and design decisions. MIT license, copyright 2026 maomao-1937.
