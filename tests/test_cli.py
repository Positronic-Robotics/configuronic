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
        assert 'a: <REQUIRED>' in out
        assert 'b: <REQUIRED>' in out


def test_cli_help_prints_docstring(capfd):
    @cfn.config()
    def identity(a, b):
        """This is a test function."""
        print(a, b)

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli(identity)
        out, err = capfd.readouterr()
        assert 'This is a test function.' in out


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
        assert 'a.req_arg: <REQUIRED>' in out


def test_cli_multiple_commands_call_overrides_arg(capfd):
    @cfn.config()
    def func1(a):
        print(f'a: {a}')

    @cfn.config()
    def func2(b):
        print(f'b: {b}')

    with patch('sys.argv', ['script.py', 'func1', '--a=1']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert out == 'a: 1\n'


def test_cli_multiple_commands_help_prints_commands_list(capfd):
    @cfn.config()
    def func1(a):
        """Docstring for func1"""
        print(f'a: {a}')

    @cfn.config()
    def func2(b):
        """Docstring for func2"""
        print(f'b: {b}')

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert 'python script.py func1 --a=<REQUIRED> # Docstring for func1' in out
        assert 'python script.py func2 --b=<REQUIRED> # Docstring for func2' in out


def test_cli_multiple_commands_no_docstring_help_prints_commands_list(capfd):
    @cfn.config()
    def func_no_docstring(a):
        print(f'a: {a}')

    with patch('sys.argv', ['script.py', '--help']):
        cfn.cli({'func_no_docstring': func_no_docstring})
        out, err = capfd.readouterr()
        assert 'python script.py func_no_docstring --a=<REQUIRED>' in out


def test_cli_multiple_commands_help_prints_command_help(capfd):
    @cfn.config()
    def func1(a):
        print(f'a: {a}')

    @cfn.config()
    def func2(b):
        print(f'b: {b}')

    with patch('sys.argv', ['script.py', 'func1', '--help']):
        cfn.cli({'func1': func1, 'func2': func2})
        out, err = capfd.readouterr()
        assert 'a: <REQUIRED>' in out


def test_cli_multiple_commands_unknown_command_raises_error(capfd):
    @cfn.config()
    def func1(a):
        print(f'a: {a}')

    @cfn.config()
    def func2(b):
        print(f'b: {b}')

    with patch('sys.argv', ['script.py', 'func3']):
        with pytest.raises(ValueError) as e:
            cfn.cli({'func1': func1, 'func2': func2})
        assert "Command 'func3' not found. Available commands: ['func1', 'func2']" in str(e.value)


def test_cli_multiple_commands_unknown_command_with_help_raises_error(capfd):
    @cfn.config()
    def func1(a):
        print(f'a: {a}')

    @cfn.config()
    def func2(b):
        print(f'b: {b}')

    with patch('sys.argv', ['script.py', 'func3', '--help']):
        with pytest.raises(ValueError) as e:
            cfn.cli({'func1': func1, 'func2': func2})
        assert "Command 'func3' not found. Available commands: ['func1', 'func2']" in str(e.value)


def test_cli_multiple_commands_print_help_if_no_args_provided(capfd):
    @cfn.config()
    def func1(a):
        print(f'a: {a}')

    with patch('sys.argv', ['script.py']):
        cfn.cli({'func1': func1})
        out, err = capfd.readouterr()
        assert 'python script.py func1 --a=<REQUIRED>' in out


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


def test_cli_nested_tree_dispatches_to_leaf(capfd):
    @cfn.config()
    def add(a, b):
        print(f'sum: {a + b}')

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py', 'math', 'add', '--a=1', '--b=2']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert out == 'sum: 3\n'


def test_cli_nested_tree_group_help_lists_children(capfd):
    @cfn.config()
    def add(a, b):
        """Add two numbers"""
        print(a + b)

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py', 'math', '--help']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert 'python script.py math add --a=<REQUIRED> --b=<REQUIRED> # Add two numbers' in out


def test_cli_nested_tree_bare_group_lists_children(capfd):
    @cfn.config()
    def add(a):
        print(a)

    tree = {'math': {'add': add}}
    # A bare group name (no further positional, no --help) lists the group's children.
    with patch('sys.argv', ['script.py', 'math']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert 'python script.py math add --a=<REQUIRED>' in out


def test_cli_root_help_lists_intermediate_groups(capfd):
    @cfn.config()
    def add(a):
        print(a)

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert 'python script.py math <command> ...' in out


def test_cli_flat_dotted_catalog_key_is_a_leaf(capfd):
    """The eval catalog is a flat dict of dotted keys nested under a group."""

    @cfn.config()
    def run_eval(eval_name, policy):
        print(f'{eval_name}:{policy}')

    tree = {'eval': {'run': {'sim.positronic.stack_cubes': run_eval.override(eval_name='stack_cubes')}}}
    with patch('sys.argv', ['script.py', 'eval', 'run', 'sim.positronic.stack_cubes', '--policy=remote']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert out == 'stack_cubes:remote\n'


def test_cli_nested_tree_unknown_key_reports_path(capfd):
    @cfn.config()
    def add(a):
        print(a)

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py', 'math', 'nope']):
        with pytest.raises(ValueError) as e:
            cfn.cli(tree)
        assert "Command 'nope' not found under 'math'. Available commands: ['add']" in str(e.value)


def test_cli_nested_tree_leaf_help_lists_required_args(capfd):
    @cfn.config()
    def add(a, b):
        print(a + b)

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py', 'math', 'add', '--help']):
        cfn.cli(tree)
        out, err = capfd.readouterr()
        assert 'a: <REQUIRED>' in out
        assert 'b: <REQUIRED>' in out


def test_cli_leaf_help_reflects_overrides(capfd):
    """`cmd --a=1 --help` must apply the override before printing help, so `a` is no
    longer reported as required."""

    @cfn.config()
    def add(a, b):
        print(a + b)

    with patch('sys.argv', ['script.py', 'func', '--a=1', '--help']):
        cfn.cli({'func': add})
        out, err = capfd.readouterr()
        assert 'b: <REQUIRED>' in out
        assert 'a: <REQUIRED>' not in out


def test_cli_group_rejects_unknown_option(capfd):
    """An option-looking token before any leaf is selected is a typo, not a help request."""

    @cfn.config()
    def func1(a):
        print(a)

    with patch('sys.argv', ['script.py', '--typo']):
        with pytest.raises(ValueError) as e:
            cfn.cli({'func1': func1})
        assert "Command '--typo' not found. Available commands: ['func1']" in str(e.value)


def test_cli_nested_group_rejects_unknown_option(capfd):
    @cfn.config()
    def add(a):
        print(a)

    tree = {'math': {'add': add}}
    with patch('sys.argv', ['script.py', 'math', '--typo']):
        with pytest.raises(ValueError) as e:
            cfn.cli(tree)
        assert "Command '--typo' not found under 'math'. Available commands: ['add']" in str(e.value)
