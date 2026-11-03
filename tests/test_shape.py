import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / 'sqlite_bind_shape.py'
if PRODUCT.exists():
    spec = importlib.util.spec_from_file_location('shape', PRODUCT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
else:
    m = None


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(m, 'original static scanner has not been implemented')

    def check(self, sql, data):
        return m.analyze(sql, json.dumps(data))

    def reject(self, sql, bindings='{}', code=None):
        with self.assertRaises(m.InputError) as caught:
            m.analyze(sql, bindings)
        if code:
            self.assertEqual(caught.exception.code, code)

    def test_anonymous_count(self):
        status, report = self.check('SELECT ?, ?', [1, 2])
        self.assertEqual(status, 0)
        self.assertEqual(report['occurrences'], 2)
        self.assertEqual(self.check('SELECT ?, ?', [1])[0], 1)

    def test_repeated_names_and_mixed_prefixes(self):
        status, r = self.check('SELECT :secret, :secret, @secret, $other', {'secret': 4, 'other': 5})
        self.assertEqual((status, r['occurrences'], r['unique_prefixed_slots'], r['distinct_binding_names']), (0, 4, 3, 2))
        self.assertEqual(r['parameters'][0], {'ordinal': 1, 'position': 8, 'prefix': ':'})

    def test_quote_and_comment_false_parameters(self):
        sql = '''SELECT '?', 'it''s :no', "a""@no", `a``$no`, [a?], ? -- :no\n/* @no */'''
        self.assertEqual(self.check(sql, [7])[1]['occurrences'], 1)
        self.assertEqual(self.check('-- ?\r :no', [])[0], 0)

    def test_bracket_first_close_and_nested_ambiguity(self):
        self.assertEqual(self.check('SELECT [a], ?', [0])[0], 0)
        self.reject('SELECT [[a?]]')

    def test_unicode_character_positions(self):
        self.assertEqual(self.check("SELECT '猫', :x", {'x': 1})[1]['parameters'][0]['position'], 13)

    def test_identifier_dollar_is_not_a_parameter(self):
        self.assertEqual(self.check('SELECT foo$bar, foo$bar$baz', [])[1]['occurrences'], 0)

    def test_lexical_only_invalid_sql_does_not_execute(self):
        self.assertEqual(self.check('invalid SQL x? DROP TABLE mystery;', [0])[0], 0)

    def test_unsupported_forms(self):
        for sql in ('SELECT ?1', 'SELECT ?0', 'SELECT ?01', 'SELECT ?999', 'SELECT :x, ?',
                    'SELECT $x::suffix(extra)', 'SELECT $x(extra)', 'SELECT :猫', 'SELECT :a猫',
                    'SELECT @9x', 'SELECT :', 'SELECT ??', 'SELECT ::x', 'SELECT :x@y', 'SELECT :x$y',
                    'SELECT ?name', 'SELECT ?猫', 'SELECT :x(extra)', 'SELECT @x(extra)'):
            with self.subTest(sql=sql):
                self.reject(sql)

    def test_unterminated_contexts(self):
        for sql in ("SELECT 'x", 'SELECT "x', 'SELECT `x', 'SELECT [x', '/* open'):
            self.reject(sql, code='SQL_CONTEXT')

    def test_binding_container_and_strict_coverage(self):
        for sql, data in [('SELECT ?', {}), ('SELECT :x', [1]), ('SELECT 1', [1]), ('SELECT 1', {'extra': 1})]:
            self.assertEqual(self.check(sql, data)[0], 1)
        for data in ([], {}):
            self.assertEqual(self.check('SELECT 1', data)[0], 0)
        status, r = self.check('SELECT :x, :y', {'x': 1, 'extra': 2})
        self.assertEqual(status, 1)
        self.assertEqual((r['missing_names'], r['extra_names']), (1, 1))

    def test_json_strictness(self):
        for raw in ('{"x":1,"x":2}', '[NaN]', '[Infinity]', '[-Infinity]', '[1e999]',
                    '["\\ud800"]', '{"\\udfff":1}', '{} trailing', 'null', '1', 'true'):
            with self.subTest(raw=raw):
                self.reject('SELECT 1', raw)

    def test_json_nested_values_are_shape_only(self):
        self.assertEqual(self.check('SELECT :x', {'x': {'nested': [1]}})[0], 0)

    def test_caps(self):
        self.reject('x' * (m.MAX_BYTES + 1), '[]', 'INPUT_LIMIT')
        self.reject('SELECT 1', ' ' * (m.MAX_BYTES + 1), 'INPUT_LIMIT')
        self.reject('SELECT ' + ','.join('?' for _ in range(m.MAX_PARAMS + 1)), '[]', 'PARAM_LIMIT')
        self.reject('SELECT :' + 'a' * (m.MAX_NAME + 1), '{}', 'PARAM_LIMIT')
        self.reject('SELECT 1', '[' * 65 + '0' + ']' * 65, 'JSON_LIMIT')
        self.reject('SELECT 1', '[' + ','.join('0' for _ in range(m.MAX_NODES)) + ']', 'JSON_LIMIT')

    def test_private_report(self):
        _, report = self.check('SELECT :SUPER_PRIVATE', {'OTHER_PRIVATE': 'VALUE_SECRET'})
        output = json.dumps(report)
        for secret in ('SUPER_PRIVATE', 'OTHER_PRIVATE', 'VALUE_SECRET', 'SELECT'):
            self.assertNotIn(secret, output)

    def test_real_sqlite_supported_oracle(self):
        cases = [('SELECT ?, ?', [3, 4]), ('SELECT :x, :x, @x, $x', {'x': 7}),
                 ("SELECT '?', :x /* ? */ -- @z\n", {'x': 2}),
                 ('SELECT 1 AS "a""?", 2 AS `b``?`, 3 AS [c?]', [])]
        with sqlite3.connect(':memory:') as con:
            for sql, values in cases:
                with self.subTest(sql=sql):
                    self.assertEqual(self.check(sql, values)[0], 0)
                    self.assertIsNotNone(con.execute(sql, values).fetchone())
            self.assertEqual(con.execute('SELECT :x, @x', {'x': 8}).fetchone(), (8, 8))
            self.assertEqual(con.execute('SELECT :x', {'x': 8, 'extra': 9}).fetchone(), (8,))
            self.assertEqual(self.check('SELECT :x', {'x': 8, 'extra': 9})[0], 1)

    def test_path_profile_before_access(self):
        bad = ['https://secret/a', 'file:///tmp/x', '//host/x', '\\\\host\\x', '/\\host/x', '\\/host/x',
               '\\\\?\\C:\\x', 'NUL', 'nul.txt', 'NUL ', 'CLOCK$', 'a/COM1.json', 'x\x00y', 'a\nsecret',
               'C:relative', 'a:stream', 'NUL .sql', 'CONIN$', 'conout$.txt']
        with patch.object(m.os, 'stat', side_effect=AssertionError('stat called')), patch('builtins.open', side_effect=AssertionError('open called')):
            for path in bad:
                with self.subTest(path=path):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(m.main(['ordinary.sql', path]), 2)
        m.validate_path('C:\\ordinary\\sample.sql')
        m.validate_path('relative/sample.sql')

    def test_files_read_only_and_private_cli_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'secret.sql', Path(tmp) / 'secret.json'
            a.write_text('SELECT :TOP_SECRET', encoding='utf-8')
            b.write_text('{"TOP_SECRET":12}', encoding='utf-8')
            before = (a.read_bytes(), b.read_bytes())
            result = subprocess.run([sys.executable, PRODUCT.name, str(a), str(b)], cwd=ROOT, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(b'TOP_SECRET', result.stdout + result.stderr)
            self.assertEqual(before, (a.read_bytes(), b.read_bytes()))
            a.write_bytes(b'\xff')
            result = subprocess.run([sys.executable, PRODUCT.name, str(a), str(b)], cwd=ROOT, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(str(a).encode(), result.stdout + result.stderr)

    def test_nonregular_and_read_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(m.InputError):
                m.read_local(tmp)
            path = Path(tmp) / 'large'
            path.write_bytes(b'x' * (m.MAX_BYTES + 1))
            with self.assertRaises(m.InputError):
                m.read_local(str(path))

    def test_actual_closed_stdout_including_help(self):
        for arguments in (['--help'], ['examples/clean.sql', 'examples/clean.json']):
            process = subprocess.Popen([sys.executable, PRODUCT.name, *arguments], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            process.stdout.close()
            err = process.stderr.read()
            process.stderr.close()
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 2, err)
            self.assertNotIn(b'Traceback', err)


if __name__ == '__main__':
    unittest.main()
