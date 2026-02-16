import subprocess
import sys


def run_main(*args):
    return subprocess.run([sys.executable, '-m', 'configuronic', *args], capture_output=True, text=True)


def test_main_resolves_and_runs_config():
    result = run_main('@tests.support_package.cfg.echo')
    assert result.returncode == 0
    assert result.stdout.strip() == 'hello'


def test_main_passes_override_params():
    result = run_main('@tests.support_package.cfg.echo', '--message=world')
    assert result.returncode == 0
    assert result.stdout.strip() == 'world'


def test_main_missing_arg_prints_usage():
    result = run_main()
    assert result.returncode == 1
    assert 'Usage:' in result.stderr


def test_main_arg_without_at_prefix_prints_usage():
    result = run_main('tests.support_package.cfg.echo')
    assert result.returncode == 1
    assert 'Usage:' in result.stderr


def test_main_invalid_import_path():
    result = run_main('@nonexistent.module.thing')
    assert result.returncode != 0


def test_main_non_config_object():
    result = run_main('@tests.support_package.b.B')
    assert result.returncode == 1
    assert 'expected a Config object' in result.stderr
