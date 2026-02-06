import subprocess
import sys
from enum import Enum

import pytest

import configuronic as cfn
import tests.support_package.cfg2


class ResolutionEnum(Enum):
    RES_1080P = '1080p'
    RES_720P = '720p'
    RES_480P = '480p'


class Env:
    def __init__(self, camera):
        self.camera = camera


class Camera:
    class InnerResolutionEnum(Enum):
        RES_1080P = '1080p'
        RES_720P = '720p'
        RES_480P = '480p'

    def __init__(self, name: str):
        self.name = name


class MultiEnv:
    def __init__(self, env1: Env, env2: Env):
        self.env1 = env1
        self.env2 = env2


def add(a, b):
    return a + b


def apply(func, a, b):
    return func(a, b)


static_object = Camera(name='Static Camera')


def test_instantiate_class_object_basic_created():
    camera_cfg = cfn.Config(Camera, name='OpenCV')

    camera_obj = camera_cfg.instantiate()

    assert isinstance(camera_obj, Camera)
    assert camera_obj.name == 'OpenCV'


def test_instantiate_class_object_with_function_created():
    add_cfg = cfn.Config(add, a=1, b=2)

    add_obj = add_cfg.instantiate()

    assert add_obj == 3


def test_instantiate_class_object_nested_created():
    camera_cfg = cfn.Config(Camera, name='OpenCV')
    env_cfg = cfn.Config(Env, camera=camera_cfg)

    env_obj = env_cfg.instantiate()

    assert isinstance(env_obj, Env)
    assert isinstance(env_obj.camera, Camera)
    assert env_obj.camera.name == 'OpenCV'


def test_instantiate_class_nested_object_overriden_with_config_created():
    opencv_camera_cfg = cfn.Config(Camera, name='OpenCV')
    luxonis_camera_cfg = cfn.Config(Camera, name='Luxonis')

    env_cfg = cfn.Config(Env, camera=opencv_camera_cfg)

    env_obj = env_cfg.override(camera=luxonis_camera_cfg).instantiate()

    assert isinstance(env_obj, Env)
    assert isinstance(env_obj.camera, Camera)
    assert env_obj.camera.name == 'Luxonis'


def test_instantiate_class_required_args_provided_with_kwargs_override_created():
    incomplete_camera_cfg = cfn.Config(Camera)

    camera_obj = incomplete_camera_cfg.override(name='OpenCV').instantiate()

    assert isinstance(camera_obj, Camera)
    assert camera_obj.name == 'OpenCV'


def test_instantiate_class_required_args_provided_with_path_to_class_created():
    incomplete_env_cfg = cfn.Config(Env)

    env_obj = incomplete_env_cfg.override(camera='@tests.test_config.static_object').instantiate()

    assert isinstance(env_obj, Env)
    assert isinstance(env_obj.camera, Camera)
    assert env_obj.camera.name == 'Static Camera'


def test_instantiate_set_leaf_value_level2_created():
    luxonis_camera_cfg = cfn.Config(Camera, name='Luxonis')
    env1_cfg = cfn.Config(Env, camera=luxonis_camera_cfg)

    env2_cfg = cfn.Config(Env)

    multi_env_cfg = cfn.Config(MultiEnv, env1=env1_cfg, env2=env2_cfg)

    new_camera_cfg = cfn.Config(Camera, name='New Camera')

    full_cfg = multi_env_cfg.override(env2=cfn.Config(Env, camera=new_camera_cfg))
    env_obj = full_cfg.instantiate()

    assert isinstance(env_obj, MultiEnv)
    assert isinstance(env_obj.env1, Env)
    assert isinstance(env_obj.env1.camera, Camera)
    assert env_obj.env1.camera.name == 'Luxonis'
    assert isinstance(env_obj.env2, Env)
    assert isinstance(env_obj.env2.camera, Camera)
    assert env_obj.env2.camera.name == 'New Camera'


def test_override_basic_keeps_original_config():
    cfg = cfn.Config(Camera, name='OpenCV')

    cfg.override(name='New Camera')

    assert cfg.kwargs['name'] == 'OpenCV'


def test_override_nested_keeps_original_config():
    cfg = cfn.Config(
        MultiEnv,
        env1=cfn.Config(Env, camera=cfn.Config(Camera, name='OpenCV')),
        env2=cfn.Config(Env, camera=cfn.Config(Camera, name='Luxonis')),
    )

    cfg.override(env2=cfn.Config(Env, camera=cfn.Config(Camera, name='New Camera')))

    assert cfg.kwargs['env2'].kwargs['camera'].kwargs['name'] == 'Luxonis'


def test_config_non_callable_target_raises_error():
    # TODO: Another posibility is to return the original object in this case
    non_callable = object()

    with pytest.raises(AssertionError):
        cfn.Config(non_callable)


def test_config_to_dict_kwargs_only_produces_correct_dict():
    cfg = cfn.Config(Camera, name='OpenCV')

    expected = {'@target': f'@{Camera.__module__}.{Camera.__name__}', 'name': 'OpenCV'}
    assert cfg._to_dict() == expected


def test_config_to_dict_kwargs_and_args_produces_correct_dict():
    cfg = cfn.Config(add, 1, b=2)

    expected = {'@target': f'@{add.__module__}.{add.__name__}', '*args': [1], 'b': 2}
    assert cfg._to_dict() == expected


def test_config_to_dict_nested_produces_correct_dict():
    cfg = cfn.Config(
        MultiEnv,
        env1=cfn.Config(Env, camera=cfn.Config(Camera, name='OpenCV')),
        env2=cfn.Config(Env, camera=cfn.Config(Camera, name='Luxonis')),
    )

    expected_dict = {
        '@target': f'@{MultiEnv.__module__}.{MultiEnv.__name__}',
        'env1': {
            '@target': f'@{Env.__module__}.{Env.__name__}',
            'camera': {'@target': f'@{Camera.__module__}.{Camera.__name__}', 'name': 'OpenCV'},
        },
        'env2': {
            '@target': f'@{Env.__module__}.{Env.__name__}',
            'camera': {'@target': f'@{Camera.__module__}.{Camera.__name__}', 'name': 'Luxonis'},
        },
    }

    assert cfg._to_dict() == expected_dict


def test_config_str_nested_produces_correct_str():
    cfg = cfn.Config(apply, func=cfn.Config(add, 1, b=2), a=3, b=4)

    # The exact format that matches the actual output from Config.__str__
    expected_str = f"""'@target': '@{apply.__module__}.{apply.__name__}'
func:
  '@target': '@{add.__module__}.{add.__name__}'
  '*args': [1]
  b: 2
a: 3
b: 4
"""

    assert str(cfg) == expected_str


def test_instantiate_not_complete_config_raises_error():
    cfg = cfn.Config(Camera)

    with pytest.raises(TypeError, match="missing 1 required positional argument: 'name'"):
        cfg.instantiate()


def test_config_as_decorator_acts_as_config_class():
    @cfn.config()
    def sum(a, b):
        return a + b

    assert sum.override(a=1, b=2).instantiate() == 3


def test_config_as_decorator_default_args_are_passed_to_target():
    @cfn.config()
    def sum(a=1, b=2):
        return a + b

    assert sum.instantiate() == 3


def test_config_as_decorator_override_values_and_instantiate_works():
    @cfn.config(a=1, b=2)
    def sum(a, b):
        return a + b

    assert sum() == 3


def test_config_callable_works_with_flat_configs():
    @cfn.config(a=1, b=2)
    def sum(a, b):
        return a + b

    assert sum() == 3


def test_instantiate_with_lists_and_dicts():
    # Define some simple callables for testing
    def add(a, b):
        return a + b

    def multiply(a, b):
        return a * b

    def process_list(items):
        return sum(items)

    def process_dict(data):
        return sum(data.values())

    # Create nested configs in args
    nested_in_list = cfn.Config(
        process_list,
        [
            cfn.Config(add, 1, 2),  # This will be 3
            cfn.Config(multiply, 2, 3),  # This will be 6
            5,
        ],
    )

    # Create nested configs in kwargs
    nested_in_dict = cfn.Config(
        process_dict,
        {
            'x': cfn.Config(add, 1, 2),  # This will be 3
            'y': cfn.Config(multiply, 2, 3),  # This will be 6
            'z': 5,
        },
    )

    # Create multi-level nesting
    deeply_nested = cfn.Config(
        add,
        cfn.Config(multiply, 2, 3),  # This will be 6
        cfn.Config(
            process_dict,
            {
                'a': cfn.Config(add, 1, 2),  # This will be 3
                'b': 4,
            },
        ),  # This will be 7
    )  # Final result should be 13

    # Test nested configs in lists
    assert nested_in_list.instantiate() == 14  # 3 + 6 + 5 = 14

    # Test nested configs in dictionaries
    assert nested_in_dict.instantiate() == 14  # 3 + 6 + 5 = 14

    # Test deeply nested configs
    assert deeply_nested.instantiate() == 13  # 6 + 7 = 13

    # Test with decorator syntax and nesting
    @cfn.config()
    def complex_operation(a, items, data):
        return a + sum(items) + sum(data.values())

    result = complex_operation.override(
        a=1, items=[cfn.Config(add, 1, 2), cfn.Config(multiply, 2, 3)], data={'x': cfn.Config(add, 1, 2), 'y': 5}
    ).instantiate()

    assert result == 18  # 1 + (3 + 6) + (3 + 5) = 18


def test_instantiate_exception_during_instantiation_has_correct_path():
    def func(a, b):
        return a + b

    def bad_function(a, b):
        raise ValueError('Bad function')

    cfg = cfn.Config(func, a=cfn.Config(bad_function, a=1, b=2), b=3)

    with pytest.raises(cfn.ConfigError) as e:
        cfg.instantiate()

    assert str(e.value) == 'Error instantiating "a": Bad function'


def test_instantiate_exception_during_instantiation_has_correct_path_with_nested_configs():
    def lvl1_function(lvl1arg):
        return lvl1arg

    def lvl2_function(lvl2arg):
        return lvl2arg

    def bad_function(a, b):
        raise ValueError('Bad function')

    cfg = cfn.Config(
        lvl1_function,
        lvl1_arg=cfn.Config(
            lvl2_function,
            lvl2_arg=cfn.Config(bad_function, a=1, b=2),
        ),
    )

    with pytest.raises(cfn.ConfigError) as e:
        cfg.instantiate()

    assert str(e.value) == 'Error instantiating "lvl1_arg.lvl2_arg": Bad function'


def test_instantiate_exception_during_instantiation_has_correct_path_with_list():
    def func(list_arg):
        return list_arg[0]

    @cfn.config()
    def goob_obj():
        return 1

    @cfn.config()
    def bad_obj():
        raise ValueError('Bad object')

    cfg = cfn.Config(func, list_arg=[goob_obj, bad_obj])

    with pytest.raises(cfn.ConfigError) as e:
        cfg.instantiate()

    assert str(e.value) == 'Error instantiating "list_arg[1]": Bad object'


def test_instantiate_exception_during_instantiation_has_correct_path_with_dict():
    def func(dict_arg):
        return dict_arg['key']

    @cfn.config()
    def goob_obj():
        return 1

    @cfn.config()
    def bad_obj():
        raise ValueError('Bad object')

    cfg = cfn.Config(func, dict_arg={'key': goob_obj, 'bad_key': bad_obj})

    with pytest.raises(cfn.ConfigError) as e:
        cfg.instantiate()

    assert str(e.value) == 'Error instantiating "dict_arg["bad_key"]": Bad object'


def test_instantiate_override_with_complex_path_to_object_works():
    @cfn.config()
    def true_if_math_module(obj):
        import math

        return obj is math

    assert true_if_math_module.override(obj='@math').instantiate()


def test_instantiate_override_with_path_to_module_works():
    @cfn.config()
    def return_true(obj):
        return True

    assert return_true.override(obj='@http.HTTPStatus.OK').instantiate()


def test_override_with_single_dot_relative_path():
    camera_cfg = cfn.Config(Camera, name='OpenCV')
    env_cfg = cfn.Config(Env, camera=camera_cfg)

    env_obj = env_cfg.override(camera='.static_object').instantiate()

    assert env_obj.camera is static_object


def test_override_with_single_dot_enum_inside_class_relative_path():
    @cfn.config(status=Camera.InnerResolutionEnum.RES_1080P)
    def return_value(status):
        return status

    assert return_value.override(status='.RES_720P').instantiate() == Camera.InnerResolutionEnum.RES_720P


def test_override_with_single_dot_enum_relative_path():
    @cfn.config(status=ResolutionEnum.RES_1080P)
    def return_value(status):
        return status

    assert return_value.override(status='.RES_720P').instantiate() == ResolutionEnum.RES_720P


def test_override_with_multiple_dots_relative_path():
    from tests.support_package.b import B
    from tests.support_package.subpkg.a import A

    env_cfg = cfn.Config(Env, camera=A)

    env_obj = env_cfg.override(camera='...b.B').instantiate()

    assert env_obj.camera is B


def test_override_with_dot_from_cfg_module_applies_relative_to_cfg_module():
    from tests.support_package.cfg import a_cfg_value1

    env_cfg = cfn.Config(Env, camera=a_cfg_value1)

    env_obj = env_cfg.override(camera='.a_cfg_value2').instantiate()

    assert env_obj.camera.value == 2


def test_override_with_dot_from_copied_config_applies_relative_to_cfg_module():
    from tests.support_package.cfg2 import a_cfg_value1_copy

    env_cfg = cfn.Config(Env, camera=a_cfg_value1_copy)

    env_obj = env_cfg.override(camera='.return2').instantiate()

    assert env_obj.camera == 2


def test_override_with_dot_decorator_config_applies_relative_to_cfg_module():
    from tests.support_package.cfg2 import return1

    env_cfg = cfn.Config(Env, camera=return1)

    env_obj = env_cfg.override(camera='.return2').instantiate()

    assert env_obj.camera == 2


def test_config_callable_with_dot_from_copied_config_applies_relative_to_cfg_module():
    from tests.support_package.cfg2 import a_cfg_value1_copy

    env_cfg = cfn.Config(Env, camera=a_cfg_value1_copy)

    env_obj = env_cfg(camera='.return2')

    assert env_obj.camera == 2


def test_override_nesetd_value_with_dot_from_copied_config_applies_relative_to_cfg_module():
    from tests.support_package.cfg2 import a_nested_b_value1

    env_cfg = cfn.Config(Env, camera=a_nested_b_value1)

    env_obj = env_cfg.override(**{'camera.value': '.b_cfg_value2'}).instantiate()

    assert env_obj.camera.value.value == 2


def test_override_with_dot_from_overriden_config_applies_relative_to_cfg_module():
    from tests.support_package.cfg2 import a_cfg_value1_override_value3

    env_cfg = cfn.Config(Env, camera=a_cfg_value1_override_value3)

    env_obj = env_cfg.override(camera='.return2').instantiate()

    assert env_obj.camera == 2


def test_override_with_dot_and_string_default():
    env_cfg = cfn.Config(Env).override(camera='@tests.test_config.Camera')
    env_obj = env_cfg.override(camera='.static_object').instantiate()

    assert env_obj.camera is static_object


def test_override_with_dot_without_default_treated_as_literal():
    env_cfg = cfn.Config(Env, camera=None)

    # Leading-dot strings are treated as literals when default is not a Config
    cfg2 = env_cfg.override(camera='.static_object')
    obj = cfg2.instantiate()
    assert obj.camera == '.static_object'


def test_override_import_error_wrapped_with_context():
    env_cfg = cfn.Config(Env, camera=cfn.Config(Camera, name='OpenCV'))

    with pytest.raises(cfn.ConfigError) as exc_info:
        env_cfg.override(camera='@not.a.real.path')

    assert str(exc_info.value) == "Failed to override 'camera' with value '@not.a.real.path'"
    assert isinstance(exc_info.value.__cause__, ImportError)
    assert 'not.a.real.path' in str(exc_info.value.__cause__)


def test_override_nested_error_preserves_original_cause():
    env_cfg = cfn.Config(Env, camera=cfn.Config(Camera, name='OpenCV'))

    with pytest.raises(cfn.ConfigError) as exc_info:
        env_cfg.override(**{'camera.name.nonexistent': 'value'})

    assert str(exc_info.value) == "Failed to override 'name' with value 'value'"
    assert isinstance(exc_info.value.__cause__, cfn.ConfigError)
    assert 'Cannot set value' in str(exc_info.value.__cause__)


def test_relative_import_with_enum_default():
    """Test that relative imports work when the default is an Enum value."""
    import http

    def process_enum(enum_val):
        return enum_val.value

    # Set up a config with an enum default
    cfg = cfn.Config(process_enum, enum_val=http.HTTPStatus.OK)

    # Override with a relative import (this should work after the fix)
    result_cfg = cfg.override(enum_val='.NOT_FOUND')
    result = result_cfg.instantiate()

    assert result == 404


def test_relative_import_with_nested_enum_default():
    """Test that relative imports work when the default is a nested Enum value.

    Example: geom.Rotation.Representation.ROTVEC
    """
    import http

    def process_nested_enum(enum_val):
        return enum_val.name

    # Set up a config with a nested enum default (HTTPStatus is nested in http module)
    cfg = cfn.Config(process_nested_enum, enum_val=http.HTTPStatus.OK)

    # Override with a relative import (this should work after the fix)
    result_cfg = cfg.override(enum_val='.BAD_REQUEST')
    result = result_cfg.instantiate()

    assert result == 'BAD_REQUEST'


def identity(x):
    return x


def test_override_with_dot_resolves_against_nested_config_module():
    """
    After we copy a Config that originated in cfg2.py, overriding it
    with a relative import ('.return2') must still resolve inside the
    *cfg2* module, not configuronic.config.
    """
    top_cfg = cfn.Config(identity, x=tests.support_package.cfg2.a_cfg_value1_copy)

    result = top_cfg.override(x='.return2').instantiate()
    assert result == 2


def test_config_callable_with_dot_resolves_against_nested_config_module():
    top_cfg = cfn.Config(identity, x=tests.support_package.cfg2.a_cfg_value1_copy)
    result = top_cfg(x='.return2')
    assert result == 2


def test_config_objects_are_callable():
    """Test that Config objects and overridden Config objects are callable."""

    @cfn.config(a=1, b=2)
    def add_numbers(a, b):
        return a + b

    # Base config should be callable
    assert callable(add_numbers)
    assert add_numbers() == 3

    # Overridden config should also be callable
    overridden_config = add_numbers.override(a=5)
    assert callable(overridden_config)
    assert overridden_config() == 7

    # Calling with additional override should work
    assert add_numbers(a=10, b=20) == 30

    # Calling overridden config with additional override should work
    assert overridden_config(b=10) == 15


def test_string_override_with_leading_dot():
    @cfn.config(greeting='Hello', name='world')
    def greeting(greeting, name):
        return f'{greeting}, {name}!'

    # Because the default is a string, the leading dot is not treated as a relative import
    assert greeting.override(name='.weird_name')() == 'Hello, .weird_name!'


def test_config_with_list_arg_could_be_overridden():
    @cfn.config(a=['a', 'b', 'c'])
    def join(a):
        return ''.join(a)

    assert join.override(**{'a.0': 'X'}).instantiate() == 'Xbc'


def test_config_with_list_as_arg_preserve_list_type():
    @cfn.config(a=[1, 2, 3])
    def return_arg(a):
        return a

    assert isinstance(return_arg.override(**{'a.0': 100}).instantiate(), list)


def test_config_with_list_arg_with_nested_config_could_be_overridden():
    @cfn.config(value=1)
    def obj1(value):
        return value

    @cfn.config(value=2)
    def obj2(value):
        return value

    @cfn.config(arg=[obj1, obj2])
    def return_list(arg):
        return arg

    assert return_list.override(**{'arg.0.value': 100}).instantiate() == [100, 2]


def test_override_list_entry_resolves_relative_dot():
    import tests.support_package.cfg2 as cfg2

    @cfn.config(arg=[cfg2.a_cfg_value1_copy])
    def return_first(arg):
        return arg[0]

    # Override nested list index with a relative path; should resolve to cfg2.return2
    assert return_first.override(**{'arg.0': '.return2'}).instantiate() == 2


def test_override_list_entry_resolves_absolute_at():
    import tests.support_package.cfg2 as cfg2

    @cfn.config(arg=[cfg2.a_cfg_value1_copy])
    def return_first(arg):
        return arg[0]

    # Override nested list index with absolute import path
    assert return_first.override(**{'arg.0': '@tests.support_package.cfg2.return2'}).instantiate() == 2


def test_config_with_tuple_arg_with_nested_config_could_be_overridden():
    @cfn.config(value=1)
    def obj1(value):
        return value

    @cfn.config(value=2)
    def obj2(value):
        return value

    @cfn.config(arg=(obj1, obj2))
    def return_tuple(arg):
        return arg

    assert return_tuple.override(**{'arg.0.value': 100}).instantiate() == (100, 2)


def test_config_with_dict_arg_could_be_overridden():
    @cfn.config(arg={'a': 1, 'b': 2})
    def return_dict(arg):
        return arg

    assert return_dict.override(**{'arg.a': 100}).instantiate() == {'a': 100, 'b': 2}


def test_config_with_dict_arg_with_nested_config_could_be_overridden():
    @cfn.config(value=1)
    def obj1(value):
        return value

    @cfn.config(value=2)
    def obj2(value):
        return value

    @cfn.config(arg={'a': obj1, 'b': obj2})
    def return_dict(arg):
        return arg

    assert return_dict.override(**{'arg.a.value': 100}).instantiate() == {'a': 100, 'b': 2}


def test_override_dict_entry_resolves_relative_dot():
    import tests.support_package.cfg2 as cfg2

    @cfn.config(arg={'x': cfg2.a_cfg_value1_copy})
    def return_x(arg):
        return arg['x']

    # Override nested dict key with a relative path; should resolve to cfg2.return2
    assert return_x.override(**{'arg.x': '.return2'}).instantiate() == 2


def test_override_dict_entry_resolves_absolute_at():
    import tests.support_package.cfg2 as cfg2

    @cfn.config(arg={'x': cfg2.a_cfg_value1_copy})
    def return_x(arg):
        return arg['x']

    # Override nested dict key with absolute import path
    assert return_x.override(**{'arg.x': '@tests.support_package.cfg2.return2'}).instantiate() == 2


def test_required_args_with_no_default_values_returns_all_args():
    @cfn.config()
    def func(a, b):
        return a + b

    assert cfn.get_required_args(func) == ['a', 'b']


def test_required_args_with_default_value_in_function():
    @cfn.config()
    def func(a, b=1):
        return a + b

    assert cfn.get_required_args(func) == ['a']


def test_required_args_with_default_value_in_config():
    @cfn.config(b=1)
    def func(a, b):
        return a + b

    assert cfn.get_required_args(func) == ['a']


def test_required_args_with_default_value_in_config_and_function_returns_all_args():
    @cfn.config(a=1)
    def func(a, b=1):
        return a + b

    assert cfn.get_required_args(func) == []


def test_required_args_with_args_returns_necessary_args():
    def func(a, b, c):
        return a + b + c

    func_cfg = cfn.Config(func, 1, 2)

    assert cfn.get_required_args(func_cfg) == ['c']


def test_required_args_with_args_and_keyword_only_args_returns_necessary_args():
    def func(a, b, *, c):
        return a + b + c

    func_cfg = cfn.Config(func, 1, 2)

    assert cfn.get_required_args(func_cfg) == ['c']


def test_required_args_with_args_not_required():
    @cfn.config()
    def func(*args_name):
        return sum(args_name)

    assert cfn.get_required_args(func) == []


def test_required_args_with_kwargs_not_required():
    @cfn.config()
    def func(**kwargs_name):
        return sum(kwargs_name.values())

    assert cfn.get_required_args(func) == []


def test_required_args_with_nested_config():
    @cfn.config()
    def nested_func(req_arg):
        pass

    @cfn.config(a=nested_func)
    def func(a):
        pass

    assert cfn.get_required_args(func) == ['a.req_arg']


def test_required_args_with_nested_config_in_list():
    @cfn.config()
    def nested_func(req_arg):
        pass

    @cfn.config(a=1)
    def complete_config(a):
        pass

    @cfn.config(a=[complete_config, nested_func])
    def func(a):
        pass

    assert cfn.get_required_args(func) == ['a.1.req_arg']


def test_required_args_with_nested_config_in_dict():
    @cfn.config()
    def nested_func(req_arg):
        pass

    @cfn.config(a=1)
    def complete_config(a):
        pass

    @cfn.config(arg={'a': complete_config, 'b': nested_func})
    def func(arg):
        pass

    assert cfn.get_required_args(func) == ['arg.b.req_arg']


def test_override_existing_list_arg_reports_context_for_index_error():
    @cfn.config(a=[1, 2, 3])
    def func(a):
        return a

    with pytest.raises(cfn.ConfigError) as exc_info:
        func.override(**{'a.4': 4})

    assert str(exc_info.value) == "Failed to override 'a' with value '4'"
    assert isinstance(exc_info.value.__cause__, IndexError)
    assert 'list assignment index out of range' in str(exc_info.value.__cause__)


def test_override_non_existing_list_arg_raises_config_error():
    @cfn.config(a=[1, 2, 3])
    def func(a):
        return a

    with pytest.raises(cfn.ConfigError) as exc_info:
        func.override(**{'b.0': 4})

    assert str(exc_info.value) == "Failed to override 'b' with value '4'"
    assert isinstance(exc_info.value.__cause__, cfn.ConfigError)
    assert "Argument 'b' not found in config" in str(exc_info.value.__cause__)


def test_override_kwargs_function_with_new_argument_returns_expected_dict():
    @cfn.config()
    def func(**kwargs):
        return kwargs

    res = func.override(a=4).instantiate()

    assert res == {'a': 4}


def test_override_non_existing_nested_argument_raises_config_error():
    @cfn.config(a=1)
    def obj1(a):
        return a

    @cfn.config(b=obj1)
    def obj2(b):
        return b

    @cfn.config(arg=obj2)
    def composite_obj(arg):
        return arg

    with pytest.raises(cfn.ConfigError) as exc_info:
        composite_obj.override(**{'arg.a.b': 4}).instantiate()

    assert str(exc_info.value) == "Failed to override 'a' with value '4'"
    assert isinstance(exc_info.value.__cause__, cfn.ConfigError)
    assert "Argument 'arg.a' not found in config" in str(exc_info.value.__cause__)


def test_escape_at_sign_with_double_at():
    """Test that @@ escapes to literal @ in string values."""

    @cfn.config(message='Hello')
    def print_message(message):
        return message

    # Test that @@ becomes literal @
    result = print_message.override(message='@@this_is_literal_at_sign').instantiate()
    assert result == '@this_is_literal_at_sign'


def test_escape_at_sign_in_nested_config():
    """Test that @@ escaping works in nested configurations."""

    @cfn.config(name='default')
    def create_person(name):
        return {'name': name}

    @cfn.config(person=create_person)
    def create_profile(person):
        return person

    result = create_profile.override(**{'person.name': '@@special_name'}).instantiate()
    assert result['name'] == '@special_name'


def test_escape_at_sign_with_multiple_at_signs():
    """Test that multiple @ signs are handled correctly."""

    @cfn.config(text='default')
    def process_text(text):
        return text

    # Test multiple @ signs
    result = process_text.override(text='@@@three_at_signs').instantiate()
    assert result == '@@three_at_signs'


def test_config_args_kwargs_overlap_produces_error():
    def func(a, b):
        return a + b

    func = cfn.Config(func, 1, 2, b=3)

    with pytest.raises(TypeError, match=".* got multiple values for argument 'b'.*"):
        func()


def test_config_instantiation_string_in_decorator_resolves_properly():
    @cfn.config(a='@tests.support_package.cfg2.return1')
    def func(a):
        return a

    assert func.instantiate() == 1


def test_config_instantiation_string_in_class_resolves_properly():
    def func(a):
        return a

    func_cfg = cfn.Config(func, a='@tests.support_package.cfg2.return1')

    assert func_cfg.instantiate() == 1


def test_config_instantiation_string_positional_arg_in_class_resolves_properly():
    def func(a):
        return a

    func_cfg = cfn.Config(func, '@tests.support_package.cfg2.return1')

    assert func_cfg.instantiate() == 1


def test_config_copy_with_double_at_sign_in_decorator_produces_same_config():
    @cfn.config(a='@@some_string')
    def func(a):
        return a

    func_copy = func.copy()

    assert func_copy() == func() == '@some_string'


def test_config_copy_with_double_at_sign_in_class_positional_arg_produces_same_config():
    def func(a):
        return a

    func_cfg = cfn.Config(func, '@@some_string')

    func_copy = func_cfg.copy()

    assert func_copy() == func_cfg() == '@some_string'


def test_config_dot_string_in_decorator_is_literal():
    @cfn.config(a='.return1')
    def func(a):
        return a

    assert func() == '.return1'


def test_config_dot_string_in_class_is_literal():
    def func(x):
        return x

    cfg = cfn.Config(func, x='.return1')
    assert cfg() == '.return1'


def test_config_dot_string_positional_arg_in_class_is_literal():
    def func(x):
        return x

    cfg = cfn.Config(func, '.return1')
    assert cfg() == '.return1'


# ========================================
# Tests for array and dict config references
# ========================================


def test_override_with_list_of_absolute_references():
    """Test passing a list with absolute (@) import paths via override."""

    @cfn.config()
    def return_items(items):
        return items

    items = ['@tests.support_package.cfg2.return1', '@tests.support_package.cfg2.return2']
    result = return_items.override(items=items)
    result = result.instantiate()

    # Configs are resolved to Config objects, then instantiated to their return values
    assert result == [1, 2]


def test_override_with_list_of_mixed_references():
    """Test list override with mixed absolute and relative references.

    When overriding entire list, all relative paths resolve to config's creator module,
    NOT to individual element defaults. This is true even when defaults exist.
    """
    import tests.support_package.cfg3 as cfg3

    # cfg3.process_items has default from cfg2, but when overriding entire list,
    # all relative paths resolve to cfg3 (where config is defined)
    result = cfg3.process_items.override(
        items=['.func_a', '@tests.support_package.cfg2.return1', '.func_b', '.func_c']
    ).instantiate()

    # All relative paths resolve to cfg3, not to element defaults
    assert result == ['a', 1, 'b', 'c']


def test_override_with_empty_list():
    """Test overriding with an empty list."""

    @cfn.config(items=[1, 2, 3])
    def return_items(items):
        return items

    result = return_items.override(items=[]).instantiate()
    assert result == []


def test_override_with_list_of_configs():
    """Test passing a list of Config objects directly."""
    import tests.support_package.cfg as cfg

    @cfn.config()
    def return_items(items):
        return items

    result = return_items.override(items=[cfg.a_cfg_value1, cfg.b_cfg_value1]).instantiate()

    # Configs should be instantiated
    assert len(result) == 2
    assert result[0].value == 1
    assert result[1].value == 1


def test_override_with_dict_of_absolute_references():
    """Test passing a dict with absolute (@) import paths via override."""

    @cfn.config()
    def return_config(config):
        return config

    result = return_config.override(
        config={'func1': '@tests.support_package.cfg2.return1', 'func2': '@tests.support_package.cfg2.return2'}
    ).instantiate()

    assert result == {'func1': 1, 'func2': 2}


def test_override_with_dict_of_relative_references():
    """All items in dict override resolve relative to config's creator module.

    cfg3.process_config is defined in cfg3 but has default from cfg2.
    When overriding the entire dict, ALL relative paths resolve to cfg3.
    """
    import tests.support_package.cfg3 as cfg3

    result = cfg3.process_config.override(
        config={'key1': '@tests.support_package.cfg2.return1', 'key2': '.func_a', 'key3': '.func_c'}
    ).instantiate()

    # All relative paths resolve to cfg3 (config's creator module), not to key defaults
    assert result == {'key1': 1, 'key2': 'a', 'key3': 'c'}


def test_override_with_nested_collections():
    """Test nested lists and dicts with config references."""

    @cfn.config()
    def return_items(items):
        return items

    result = return_items.override(
        items=[
            ['@tests.support_package.cfg2.return1', '@tests.support_package.cfg2.return2'],
            {'a': '@tests.support_package.cfg2.return1', 'b': 42},
        ]
    ).instantiate()

    assert result[0] == [1, 2]
    assert result[1] == {'a': 1, 'b': 42}


def test_list_override_then_indexed_override():
    """Test that list override works, then indexed override can modify it."""
    import tests.support_package.cfg as cfg

    @cfn.config()
    def return_items(items):
        return items

    # First override with list, then indexed override can modify it
    cfg_final = return_items.override(**{
        'items': ['@tests.support_package.cfg2.return1', '@tests.support_package.cfg2.return2'],
        'items.0': cfg.a_cfg_value1,
    })

    result = cfg_final.instantiate()
    assert len(result) == 2
    assert isinstance(result[0], tests.support_package.subpkg.a.A)
    assert result[0].value == 1
    assert result[1] == 2


def test_list_override_with_literals():
    """Test that literal values (strings, numbers, etc.) work in lists."""

    @cfn.config()
    def return_items(items):
        return items

    result = return_items.override(items=['hello', 42, 3.14, None]).instantiate()
    assert result == ['hello', 42, 3.14, None]


def test_dict_override_with_mixed_types():
    """Test dict with mixed value types."""

    @cfn.config()
    def return_config(config):
        return config

    result = return_config.override(
        config={'string': 'hello', 'number': 42, 'ref': '@tests.support_package.cfg2.return1', 'none': None}
    ).instantiate()

    assert result['string'] == 'hello'
    assert result['number'] == 42
    assert result['ref'] == 1
    assert result['none'] is None


def test_list_with_escaped_at_prefix():
    """Test that @@ escapes to literal @ in lists."""

    @cfn.config()
    def return_items(items):
        return items

    result = return_items.override(items=['@@not.a.reference', 'normal']).instantiate()
    assert result == ['@not.a.reference', 'normal']


def test_literal_dot_prefix_strings_via_indexed_override():
    """Test passing literal dot-prefixed strings by using indexed override workaround.

    Full list override with '.' strings attempts relative resolution.
    To pass literals like './data' or '.env', use indexed override or
    initialize with empty strings and override later.
    """

    @cfn.config(items=['', ''])
    def return_items(items):
        return items

    # Override individual indices with literal dot-prefixed strings
    result = return_items.override(**{'items.0': './data', 'items.1': '.env'}).instantiate()
    assert result == ['./data', '.env']


def test_nested_references_resolved_at_all_depths():
    """Test that config references are resolved at all nesting levels.

    Both absolute (@) and relative (.) references should be resolved
    recursively throughout nested collections.
    """
    # Define in cfg3 module context so relative imports resolve there
    import tests.support_package.cfg3 as cfg3

    # Both top-level and nested references should resolve
    result = cfg3.return_items.override(
        items=[
            '.func_a',  # Top-level relative: resolves to cfg3.func_a
            ['@tests.support_package.cfg2.return1', '.func_b'],  # Nested: both resolve
            {'abs': '@tests.support_package.cfg2.return2', 'rel': '.func_c'},  # Nested dict: both resolve
        ]
    ).instantiate()

    assert result[0] == 'a'  # Top-level relative resolved
    assert result[1] == [1, 'b']  # Nested absolute and relative resolved
    assert result[2] == {'abs': 2, 'rel': 'c'}  # Nested dict references resolved


def test_relative_import_uses_spec_name_when_module_name_is_main():
    result = subprocess.run(
        [sys.executable, '-m', 'tests.support_package.main_runner'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f'stdout: {result.stdout}\nstderr: {result.stderr}'


if __name__ == '__main__':
    pytest.main()
