from unittest.mock import patch

import pytest

import configuronic as cfn


def test_cli_kwarg_override_overrides_value(capfd):
    @cfn.config(a=1)
    def identity(a):
        print(a)

    with patch('sys.argv', ['script.py', '--a=2']):
        cfn.cli(identity)
        out, err = capfd.readouterr()
        assert out == '2\n'


def test_cli_help_prints_has_required_args(capfd):
    @cfn.config()
    def identity(a, b):
        print(a, b)

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli(identity)
        out, err = capfd.readouterr()
        assert "a: <REQUIRED>" in out
        assert "b: <REQUIRED>" in out


def test_cli_help_prints_docstring(capfd):
    @cfn.config()
    def identity(a, b):
        """This is a test function.
        """
        print(a, b)

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli(identity)
        out, err = capfd.readouterr()
        assert "This is a test function." in out


def test_cli_help_prints_nested_required_args(capfd):
    @cfn.config()
    def nested_func(req_arg):
        pass

    @cfn.config(a=nested_func)
    def func(a):
        pass

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli(func)
        out, err = capfd.readouterr()
        assert "a.req_arg: <REQUIRED>" in out


def test_cli_multiple_commands_call_overrides_arg(capfd):
    @cfn.config()
    def func1(a):
        print(f"a: {a}")

    @cfn.config()
    def func2(b):
        print(f"b: {b}")

    with patch('sys.argv', ['script.py', 'func1', '--a=1']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert out == 'a: 1\n'

def test_cli_multiple_commands_help_prints_commands_list(capfd):
    @cfn.config()
    def func1(a):
        """Docstring for func1"""
        print(f"a: {a}")

    @cfn.config()
    def func2(b):
        """Docstring for func2"""
        print(f"b: {b}")

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert "python script.py func1 --a=<REQUIRED> # Docstring for func1" in out
        assert "python script.py func2 --b=<REQUIRED> # Docstring for func2" in out


def test_cli_multiple_commands_no_docstring_help_prints_commands_list(capfd):
    @cfn.config()
    def func_no_docstring(a):
        print(f"a: {a}")

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli({'func_no_docstring': func_no_docstring})
        out, err = capfd.readouterr()
        assert "python script.py func_no_docstring --a=<REQUIRED>" in out


def test_cli_multiple_commands_help_prints_command_help(capfd):
    @cfn.config()
    def func1(a):
        print(f"a: {a}")

    @cfn.config()
    def func2(b):
        print(f"b: {b}")

    with patch('sys.argv', ['script.py', 'func1', '--help']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert "a: <REQUIRED>" in out


def test_cli_multiple_commands_unknown_command_raises_error(capfd):
    @cfn.config()
    def func1(a):
        print(f"a: {a}")

    @cfn.config()
    def func2(b):
        print(f"b: {b}")

    with patch('sys.argv', ['script.py', 'func3']):
        with pytest.raises(ValueError) as e:
            cfn.cli({'func1': func1, 'func2': func2})
        assert "Command 'func3' not found. Available commands: ['func1', 'func2']" in str(e.value)


def test_cli_multiple_commands_unknown_command_with_help_raises_error(capfd):
    @cfn.config()
    def func1(a):
        print(f"a: {a}")

    @cfn.config()
    def func2(b):
        print(f"b: {b}")

    with patch('sys.argv', ['script.py', 'func3', '--help']):
        with pytest.raises(ValueError) as e:
            cfn.cli({'func1': func1, 'func2': func2})
        assert "Command 'func3' not found. Available commands: ['func1', 'func2']" in str(e.value)


def test_cli_multiple_commands_print_help_if_no_args_provided(capfd):
    @cfn.config()
    def func1(a):
        print(f"a: {a}")

    with patch('sys.argv', ['script.py']):
        cfn.cli({'func1': func1})
        out, err = capfd.readouterr()
        assert "python script.py func1 --a=<REQUIRED>" in out


def test_cli_accepts_leading_dot_strings_as_literals(capfd):
    @cfn.config()
    def echo(a):
        print(a)

    # '../data' should be treated as a literal string
    with patch('sys.argv', ['script.py', '--a=../data']):
        cfn.cli(echo)
        out, err = capfd.readouterr()
        assert out.strip() == '../data'

    # './file' should be treated as a literal string
    with patch('sys.argv', ['script.py', '--a=./file']):
        cfn.cli(echo)
        out, err = capfd.readouterr()
        assert out.strip() == './file'

    # '.env' should be treated as a literal string
    with patch('sys.argv', ['script.py', '--a=.env']):
        cfn.cli(echo)
        out, err = capfd.readouterr()
        assert out.strip() == '.env'
