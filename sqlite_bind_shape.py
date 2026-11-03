#!/usr/bin/env python3
"""Read-only lexical placeholder coverage for a bounded SQLite subset."""

import json
import math
import os
import re
import stat
import sys

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 100_000
MAX_PARAMS = 10_000
MAX_NAME = 256
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
DRIVE = re.compile(r'^[A-Za-z]:[\\/]')
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$', re.I)


class InputError(Exception):
    """Only fixed public codes may cross the CLI boundary."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_path(path):
    """Refuse remote/device/ambiguous spellings before filesystem access."""
    if not isinstance(path, str) or not path or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise InputError('PATH_REFUSED')
    normalized = path.replace('\\', '/')
    if normalized.startswith('//'):
        raise InputError('PATH_REFUSED')
    tail = normalized[2:] if DRIVE.match(path) else normalized
    if ':' in tail:
        raise InputError('PATH_REFUSED')
    for component in tail.split('/'):
        stem = component.split('.', 1)[0].rstrip(' .')
        if RESERVED.fullmatch(stem):
            raise InputError('PATH_REFUSED')


def read_local(path):
    validate_path(path)
    metadata = os.stat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise InputError('FILE_TYPE')
    if metadata.st_size > MAX_BYTES:
        raise InputError('INPUT_LIMIT')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise InputError('FILE_TYPE')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InputError('INPUT_LIMIT')
    return raw.decode('utf-8-sig')


def bounded_text(text):
    if not isinstance(text, str):
        raise InputError('INPUT_INVALID')
    try:
        size = len(text.encode('utf-8'))
    except UnicodeError:
        raise InputError('INPUT_INVALID') from None
    if size > MAX_BYTES:
        raise InputError('INPUT_LIMIT')


def strict_json(text):
    bounded_text(text)
    # Preflight container depth before invoking the recursive stdlib parser.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_DEPTH:
                raise InputError('JSON_LIMIT')
        elif char in ']}':
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError('JSON_INVALID')
            result[key] = value
        return result

    def constant(_):
        raise InputError('JSON_INVALID')

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError):
        raise InputError('JSON_INVALID') from None
    pending, nodes = [value], 0
    while pending:
        item = pending.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise InputError('JSON_LIMIT')
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise InputError('JSON_INVALID')
        elif isinstance(item, float) and not math.isfinite(item):
            raise InputError('JSON_INVALID')
    if not isinstance(value, (dict, list)):
        raise InputError('JSON_CONTAINER')
    return value


def identifier_start(char):
    return char == '_' or char.isalpha() or ord(char) >= 128


def identifier_tail(char):
    return identifier_start(char) or char.isdigit() or char == '$'


def scan(sql):
    bounded_text(sql)
    if '\x00' in sql:
        raise InputError('SQL_CONTEXT')
    parameters, slots, names = [], set(), set()
    mode = None
    i, length = 0, len(sql)
    while i < length:
        char = sql[i]
        if sql.startswith('--', i):
            end = sql.find('\n', i + 2)
            i = length if end < 0 else end + 1
            continue
        if sql.startswith('/*', i):
            end = sql.find('*/', i + 2)
            if end < 0:
                raise InputError('SQL_CONTEXT')
            i = end + 2
            continue
        if char in "'\"`[":
            close = ']' if char == '[' else char
            i += 1
            while True:
                if i >= length:
                    raise InputError('SQL_CONTEXT')
                if char == '[' and sql[i] == '[':
                    raise InputError('SQL_UNSUPPORTED')
                if sql[i] == close:
                    i += 1
                    if char != '[' and i < length and sql[i] == close:
                        i += 1
                        continue
                    break
                i += 1
            continue
        if identifier_start(char):
            i += 1
            while i < length and identifier_tail(sql[i]):
                i += 1
            continue
        if char not in '?:@$':
            i += 1
            continue
        start = i
        if char == '?':
            i += 1
            if i < length and (identifier_tail(sql[i]) or sql[i] in '?:@'):
                raise InputError('SQL_UNSUPPORTED')
            current = 'anonymous'
        else:
            match = NAME.match(sql, i + 1)
            if match is None:
                raise InputError('SQL_UNSUPPORTED')
            name = match.group()
            if len(name) > MAX_NAME:
                raise InputError('PARAM_LIMIT')
            i = match.end()
            if i < length and (identifier_tail(sql[i]) or sql[i] in ':@?$('):
                raise InputError('SQL_UNSUPPORTED')
            slots.add(char + name)
            names.add(name)
            current = 'named'
        if mode is not None and mode != current:
            raise InputError('SQL_UNSUPPORTED')
        mode = current
        parameters.append({'ordinal': len(parameters) + 1, 'position': start + 1, 'prefix': char})
        if len(parameters) > MAX_PARAMS:
            raise InputError('PARAM_LIMIT')
    return mode, parameters, slots, names


def analyze(sql, binding_text):
    mode, parameters, slots, names = scan(sql)
    bindings = strict_json(binding_text)
    findings = []
    missing = extra = 0
    if mode == 'anonymous':
        if not isinstance(bindings, list):
            findings.append('BINDING_CONTAINER')
        elif len(bindings) != len(parameters):
            findings.append('POSITIONAL_COUNT')
    elif mode == 'named':
        if not isinstance(bindings, dict):
            findings.append('BINDING_CONTAINER')
        else:
            missing = len(names - bindings.keys())
            extra = len(bindings.keys() - names)
            if missing:
                findings.append('MISSING_NAMES')
            if extra:
                findings.append('EXTRA_NAMES')
    elif bindings:
        findings.append('UNUSED_BINDINGS')
    return int(bool(findings)), {
        'code': 'MISMATCH' if findings else 'CLEAN',
        'occurrences': len(parameters),
        'unique_prefixed_slots': len(slots) if mode == 'named' else len(parameters),
        'distinct_binding_names': len(names),
        'binding_items': len(bindings),
        'missing_names': missing,
        'extra_names': extra,
        'findings': findings,
        'parameters': parameters,
    }


def emit(report):
    sys.stdout.write(json.dumps(report, ensure_ascii=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments == ['--help']:
        sys.stdout.write('Usage: python sqlite_bind_shape.py SQLFILE BINDINGSJSON\n'
                         'Read-only static placeholder coverage. Exit 0 clean, 1 mismatch, 2 refused/error.\n')
        sys.stdout.flush()
        return 0
    try:
        if len(arguments) != 2:
            raise InputError('USAGE')
        # Validate BOTH spellings before stat/open of either one.
        for argument in arguments:
            validate_path(argument)
        sql, bindings = read_local(arguments[0]), read_local(arguments[1])
        status, report = analyze(sql, bindings)
    except InputError as error:
        status, report = 2, {'code': error.code}
    except (OSError, UnicodeError, ValueError, MemoryError, RecursionError):
        status, report = 2, {'code': 'INPUT_ERROR'}
    emit(report)
    return status


if __name__ == '__main__':
    try:
        exit_code = main()
    except (BrokenPipeError, OSError):
        # Avoid Python's shutdown flush changing an intentional error into 120.
        sys.stdout = None
        exit_code = 2
    raise SystemExit(exit_code)
