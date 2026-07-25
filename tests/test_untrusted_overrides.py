"""Tests for applying overrides whose values come from an untrusted source.

See issue #36: values that come off the network must be able to tune arguments but never
name an object to import.
"""

import copy
import pickle
import sys

import pytest

import configuronic as cfn
from tests.support_package.subpkg.a import A


class Camera:
    def __init__(self, name: str = 'default', fps: int = 30):
        self.name = name
        self.fps = fps


class Env:
    def __init__(self, camera, path: str = '/data', paths: list | None = None):
        self.camera = camera
        self.path = path
        self.paths = paths


def _env_config() -> cfn.Config:
    return cfn.Config(Env, camera=cfn.Config(Camera))


# --- override_data: plain data still works ------------------------------------------------


def test_override_data_applies_scalar_override():
    env = _env_config().override_data(**{'camera.fps': 10})

    assert env.instantiate().camera.fps == 10


def test_override_data_applies_container_values():
    env = _env_config().override_data(paths=['a', 'b'], **{'camera.name': 'left'})

    instance = env.instantiate()
    assert instance.paths == ['a', 'b']
    assert instance.camera.name == 'left'


def test_override_data_does_not_mutate_base_config():
    base = _env_config()

    base.override_data(**{'camera.fps': 10})

    assert base.instantiate().camera.fps == 30


def test_override_data_accepts_config_value_from_calling_code():
    # The guarantee constrains *strings* (the only thing external data carries), not the
    # caller: our own code can still pass a Config as a value.
    env = _env_config().override_data(camera=cfn.Config(Camera, name='right'))

    assert env.instantiate().camera.name == 'right'


def test_override_data_keeps_leading_dot_string_that_is_not_an_import():
    # 'path' defaults to a plain string, so there is no base to resolve against and
    # './data' is a literal here — same as with override().
    env = _env_config().override_data(path='./data')

    assert env.instantiate().path == './data'


def test_override_data_keeps_leading_dot_string_in_indexed_override():
    env = _env_config().override_data(paths=['x', 'y'], **{'paths.0': '../data'})

    assert env.instantiate().paths == ['../data', 'y']


def test_override_data_keeps_at_sign_that_does_not_lead():
    env = _env_config().override_data(path='user@example.com')

    assert env.instantiate().path == 'user@example.com'


# --- override_data: import strings are refused --------------------------------------------


def test_override_data_rejects_absolute_import():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(camera='@os.system')

    assert exc_info.value.key == 'camera'
    assert exc_info.value.value == '@os.system'
    assert "'camera'" in str(exc_info.value)
    assert '@os.system' in str(exc_info.value)


def test_override_data_rejects_relative_import_escaping_the_package():
    # A relative override is no safer than an absolute one: leading dots walk up the module
    # tree from the current value's module and enough of them leave the package. The base
    # here is this test module, so three dots reach the top level. The override() assertion
    # is deliberate — if resolution ever stops reaching os.system, this guard test would be
    # passing for the wrong reason.
    escape = '...os.system'

    assert _env_config().override(camera=escape).kwargs['camera'] is __import__('os').system

    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(camera=escape)

    assert exc_info.value.key == 'camera'
    assert exc_info.value.value == escape


def test_override_data_rejects_relative_import_before_importing_anything():
    tripwire = 'tests.support_package.import_tripwire'
    assert tripwire not in sys.modules, 'tripwire module must stay unimported for this test to mean anything'

    with pytest.raises(cfn.ImportNotAllowedError):
        _env_config().override_data(camera='@tests.support_package.import_tripwire.value')

    assert tripwire not in sys.modules


def test_override_data_rejects_relative_import_that_would_not_resolve():
    # Rejection is about the syntax, not about whether the import happens to succeed.
    with pytest.raises(cfn.ImportNotAllowedError):
        _env_config().override_data(camera='.NoSuchObject')


def test_override_data_reports_full_dotted_key():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(**{'camera.name': '@os.system'})

    assert exc_info.value.key == 'camera.name'


def test_override_data_rejects_import_nested_in_list():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(paths=['ok', '@os.system'])

    assert exc_info.value.key == 'paths[1]'
    assert exc_info.value.value == '@os.system'


def test_override_data_rejects_import_nested_in_dict():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(paths={'left': '@os.system'})

    assert exc_info.value.key == "paths['left']"


def test_override_data_rejects_import_nested_deeply():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(paths=[{'left': ['@os.system']}])

    assert exc_info.value.key == "paths[0]['left'][0]"


def test_override_data_rejects_relative_import_nested_in_list():
    # Inside containers every leading-dot string resolves against the config, so the
    # relative form must be refused there too.
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(paths=['...os.system'])

    assert exc_info.value.key == 'paths[0]'


def test_override_data_rejects_import_in_positional_argument():
    cfg = cfn.Config(Env, cfn.Config(Camera))

    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        cfg.override_data(**{'0': '@os.system'})

    assert exc_info.value.key == '0'


def test_override_data_rejects_escaped_at_prefix():
    # '@@x' is override()'s escape for the literal '@x'. Storing it would plant an import
    # base, so override_data refuses it before unescaping.
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(path='@@os.system')

    assert exc_info.value.value == '@@os.system'


def test_override_data_cannot_plant_a_base_for_a_later_relative_override():
    tripwire = 'tests.support_package.import_tripwire'
    assert tripwire not in sys.modules, 'tripwire module must stay unimported for this test to mean anything'
    cfg = cfn.Config(Env, camera=cfn.Config(Camera))

    # Were the escape accepted, `camera` would hold the literal '@tests...import_tripwire.x',
    # which _can_resolve_relative treats as a base — so this later trusted relative override
    # would import a module the untrusted caller named.
    with pytest.raises(cfn.ImportNotAllowedError):
        cfg.override_data(camera=f'@@{tripwire}.x').override(camera='.value')

    assert tripwire not in sys.modules


def test_override_data_cannot_plant_a_base_inside_a_container():
    cfg = cfn.Config(Env, paths=['x'])

    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        cfg.override_data(**{'paths.0': '@@tests.support_package.cfg.echo'})

    assert exc_info.value.key == 'paths.0'


def test_import_not_allowed_error_survives_pickling():
    # The advertised use case is a server, where the override may run in a worker process
    # and the exception is pickled back to the request handler.
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(camera='@os.system')

    restored = pickle.loads(pickle.dumps(exc_info.value))

    assert restored.key == 'camera'
    assert restored.value == '@os.system'
    assert str(restored) == str(exc_info.value)


def test_import_not_allowed_error_survives_copying():
    with pytest.raises(cfn.ImportNotAllowedError) as exc_info:
        _env_config().override_data(camera='@os.system')

    assert copy.copy(exc_info.value).key == 'camera'
    assert copy.deepcopy(exc_info.value).value == '@os.system'


def test_override_data_rejection_is_a_config_error():
    with pytest.raises(cfn.ConfigError):
        _env_config().override_data(camera='@os.system')


def test_override_data_rejection_leaves_base_config_untouched():
    base = _env_config()

    with pytest.raises(cfn.ImportNotAllowedError):
        base.override_data(**{'camera.fps': 10, 'camera.name': '@os.system'})

    instance = base.instantiate()
    assert instance.camera.fps == 30
    assert instance.camera.name == 'default'


def test_override_data_still_reports_unknown_keys():
    with pytest.raises(cfn.ConfigError) as exc_info:
        _env_config().override_data(**{'nonexistent.fps': 10})

    assert "Failed to override 'nonexistent.fps'" in str(exc_info.value)


def test_override_keeps_resolving_imports():
    # override() is unchanged: import strings are still resolved there.
    env = _env_config().override(camera='@tests.support_package.subpkg.a.A')

    assert env.kwargs['camera'] is A
