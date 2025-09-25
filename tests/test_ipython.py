import pytest
from IPython import InteractiveShell

import configuronic as cfn


def test_config_class_could_be_created_in_ipython():
    shell = InteractiveShell.instance()
    result = shell.run_cell(
        "import configuronic as cfn\n"
        "def add(a, b): return a + b\n"
        "add = cfn.Config(add, a=1, b=2)\n"
        "assert add() == 3"
    )
    result.raise_error()


def test_config_decorator_could_be_created_in_ipython():
    shell = InteractiveShell.instance()
    result = shell.run_cell(
        "import configuronic as cfn\n"
        "@cfn.config(a=1, b=2)\n"
        "def add(a, b): return a + b\n"
        "assert add() == 3"
    )
    result.raise_error()


def test_config_relative_override_decorator_works_in_ipython():
    shell = InteractiveShell.instance()
    result = shell.run_cell(
        "import configuronic as cfn\n"
        "@cfn.config(val=1)\n"
        "def fn(val): return val\n"
        "def add(a, b): return a + b\n"
        "add = cfn.Config(add, a=fn, b=2)\n"
        "add_override = add.override(a='.fn')\n"
    )
    with pytest.raises(cfn.ConfigError) as exc_info:
        result.raise_error()

    assert isinstance(exc_info.value.__cause__, AssertionError)
    assert (
        "Config was created in an unknown module. Probably in IPython interactive shell. "
        "Consider moving the config to a module."
        in str(exc_info.value.__cause__)
    )


def test_config_relative_override_class_works_in_ipython():
    shell = InteractiveShell.instance()
    result = shell.run_cell(
        "import configuronic as cfn\n"
        "def fn(val): return val\n"
        "fn = cfn.Config(fn, val=1)\n"
        "def add(a, b): return a + b\n"
        "add = cfn.Config(add, a=fn, b=2)\n"
        "add_override = add.override(a='.fn')\n"
    )
    with pytest.raises(cfn.ConfigError) as exc_info:
        result.raise_error()

    assert isinstance(exc_info.value.__cause__, AssertionError)
    assert (
        "Config was created in an unknown module. Probably in IPython interactive shell. "
        "Consider moving the config to a module."
        in str(exc_info.value.__cause__)
    )
