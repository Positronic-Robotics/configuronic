from unittest.mock import patch

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
