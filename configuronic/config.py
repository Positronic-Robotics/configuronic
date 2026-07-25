from __future__ import annotations

import importlib
import inspect
import posixpath
from collections import deque
from collections.abc import Callable
from types import ModuleType
from typing import Any

import yaml

INSTANTIATE_PREFIX = '@'
RELATIVE_PATH_PREFIX = '.'


class ConfigError(Exception):
    pass


class ImportNotAllowedError(ConfigError):
    """Raised when an override value uses import syntax where imports are not allowed.

    Raised by :meth:`Config.override_data`, which applies overrides with values
    interpreted strictly as data. The offending key and value are available as
    attributes so a caller can report them back to whoever supplied the value.

    Attributes:
        key: Dotted path of the rejected override. Values nested inside a list or dict
            carry their position, e.g. ``cameras[0]`` or ``codecs['left']``.
        value: The rejected string value.
    """

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value
        super().__init__(
            f"Override '{key}' has value {value!r}, which configuronic would read as import syntax: a leading "
            f"'{INSTANTIATE_PREFIX}' (absolute) or '{RELATIVE_PATH_PREFIX}' (relative to the current value) names a "
            'Python object to import. This override accepts plain data only.'
        )

    def __reduce__(self):
        # Exception.__reduce__ rebuilds from `args`, which holds only the formatted message,
        # so the default would call __init__ with one argument. Servers pickle exceptions
        # back from worker processes, so keep the two-argument form reconstructible.
        return (self.__class__, (self.key, self.value))


def _to_dict(obj):
    if isinstance(obj, Config):
        return obj._to_dict()
    elif isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    else:
        return obj


def _copy_value(value):
    """Recursively copy a config value so variants don't share mutable state.

    Nested ``Config`` instances are copied; ``dict``/``list``/``tuple`` containers are
    rebuilt so overriding through them (e.g. ``cameras.left.fps``) never mutates the
    base. Other values (ints, strings, arbitrary objects) are shared by reference —
    overrides replace them rather than mutate them in place.
    """
    if isinstance(value, Config):
        return value._copy()
    elif isinstance(value, dict):
        return {k: _copy_value(v) for k, v in value.items()}
    elif isinstance(value, list | tuple):
        return type(value)(_copy_value(v) for v in value)
    else:
        return value


def _determine_module_by_path(path: str) -> tuple[str, str]:
    module_path = path.split('.')
    object_path = deque([])

    while len(module_path) > 0:
        try:
            possible_module_path = '.'.join(module_path)
            importlib.import_module(possible_module_path)
            return possible_module_path, '.'.join(object_path)
        except ModuleNotFoundError:
            object_path.appendleft(module_path.pop())

    raise ImportError(f'Module not found for path: {path}')


def _get_object_from_path(module: Any, object_path: str) -> Any:
    x = module
    if object_path:
        for part in object_path.split('.'):
            x = getattr(x, part)
    return x


def _import_object_from_path(path: str) -> Any:
    """
    Import an object from a string path starting with '@'.

    Args:
        path (str): Path to the object in the format "@module.submodule.object"

    Returns:
        The imported object

    Raises:
        ImportError: If the module or object cannot be imported
    """
    assert path.startswith(INSTANTIATE_PREFIX), f"Path must start with '{INSTANTIATE_PREFIX}'"

    # Remove the leading '@'
    path = path[len(INSTANTIATE_PREFIX) :]

    module_path, object_path = _determine_module_by_path(path)

    # Import the module
    module = importlib.import_module(module_path)
    obj = _get_object_from_path(module, object_path)
    return obj


def _get_base_path_from_default(default: Any) -> str:
    """Extract base path from different types of default values."""
    if isinstance(default, Config):
        assert default._creator_module is not None, (
            'Config was created in an unknown module. Probably in IPython interactive shell. '
            'Consider moving the config to a module.'
        )
        module = default._creator_module
        name = getattr(module.__spec__, 'name', None) if hasattr(module, '__spec__') else None
        name = name or module.__name__
        return name + '.' + 'stub_name'
    elif isinstance(default, str):
        return default.lstrip(INSTANTIATE_PREFIX)
    elif hasattr(default, '__module__') and hasattr(default, '__name__'):
        return f'{default.__module__}.{default.__name__}'
    elif hasattr(default, '__class__') and hasattr(default, 'name'):  # Handle Enum values
        enum_class = default.__class__
        return f'{enum_class.__module__}.{enum_class.__qualname__}.{default.name}'
    else:
        raise ValueError(
            'Default value must be Config, import string, an object with __module__ and __name__, or an Enum value'
        )


def _construct_relative_path(value: str, base_path: str):
    leading = 0
    for leading in range(len(value)):
        if value[leading] != RELATIVE_PATH_PREFIX:
            break

    assert '🤷‍♂️' not in value, 'Configuronic does not support relative imports with 🤷‍♂️. Sorry 🤷‍♂️'
    value = '🤷‍♂️' * leading + value[leading:]

    path = base_path + value
    unix_like_path = path.replace('.', '/').replace('🤷‍♂️', '/../')
    unix_like_norm_path = posixpath.normpath(unix_like_path)
    module_path = unix_like_norm_path.replace('/', '.')
    return module_path


def _resolve_relative_import(value: str, default: Any) -> Any:
    """Resolve a relative import path (starting with '.')."""
    if default is None:
        raise ValueError('Relative import used with no default value')

    base_path = _get_base_path_from_default(default)
    new_path = _construct_relative_path(value, base_path)

    try:
        return _import_object_from_path(f'{INSTANTIATE_PREFIX}{new_path}')
    except (ImportError, ModuleNotFoundError, AttributeError) as e:
        # Check if this looks like a filesystem path rather than a module path
        hint = (
            f'If you meant dot-prefixed string "{value}" instead of relative import "{new_path}",'
            'please use indexed override "--key.idx={value}"',
        )
        raise ImportError(f'Failed to resolve relative import {value} to module {new_path}{hint}') from e


def _can_resolve_relative(default: Any | None) -> bool:
    """Return True if `default` provides a base for relative resolution.

    We allow relative resolution when default is:
    - a Config instance (nested config), or
    - an importable object (has __module__ and __name__), or
    - an Enum value (has class and name), or
    - a string that starts with '@' (import path string)
    """
    if isinstance(default, Config):
        return True
    if isinstance(default, str):
        return default.startswith(INSTANTIATE_PREFIX)
    if hasattr(default, '__module__') and hasattr(default, '__name__'):
        return True
    if hasattr(default, '__class__') and hasattr(default, 'name'):
        return True
    return False


def _resolve_value(
    value: Any,
    default: Any | None = None,
    config: Config | None = None,
    resolve_imports: bool = True,
    key: str = '',
) -> Any:
    """Resolve special strings to actual Python objects.

    Supports two prefixes:

    - ``@`` - absolute import path of the object to instantiate
    - ``.`` - relative path resolution when there's a suitable base: a nested
      :class:`Config`, an importable object (class/function), an Enum value, or
      a string starting with ``@``. Otherwise, treat leading-dot strings as
      literals (e.g., ``../data``, ``./file``, ``.env``).

    For lists and dicts:
    - Both absolute (``@``) and relative (``.``) references are resolved recursively at all nesting levels
    - Nested collections inherit the same resolution context from their parent

    When ``resolve_imports`` is False, every value that *would* have been resolved as an
    import raises :class:`ImportNotAllowedError` instead — at any nesting depth. Values
    that are not import references (including leading-dot strings with no base to resolve
    against, such as ``./data``) are returned unchanged, exactly as they would be with
    ``resolve_imports=True``. ``key`` is the location reported in that error; callers
    prepend the override key they were given.
    """
    if isinstance(value, str):
        if value.startswith(INSTANTIATE_PREFIX):
            if not resolve_imports:
                # Refused *before* the '@@' escape is applied. An escaped value is stored as a
                # literal '@...' string, and `_can_resolve_relative` accepts any such string as
                # an import base — so a later trusted relative override on the same key would
                # resolve against a path this caller chose. Storing one is planting an import.
                raise ImportNotAllowedError(key, value)
            elif value[len(INSTANTIATE_PREFIX) :].startswith(INSTANTIATE_PREFIX):
                return value[len(INSTANTIATE_PREFIX) :]
            else:
                return _import_object_from_path(value)
        # Only resolve relative imports when `default` provides a valid base.
        # Treat all other leading-dot strings as literals (e.g., '../data', '.env').
        elif value.startswith(RELATIVE_PATH_PREFIX) and _can_resolve_relative(default):
            if not resolve_imports:
                raise ImportNotAllowedError(key, value)
            return _resolve_relative_import(value, default)
        else:
            return value
    elif isinstance(value, list | tuple):
        return type(value)(
            _resolve_value(item, default=config, config=config, resolve_imports=resolve_imports, key=f'{key}[{i}]')
            for i, item in enumerate(value)
        )
    elif isinstance(value, dict):
        return {
            k: _resolve_value(v, default=config, config=config, resolve_imports=resolve_imports, key=f'{key}[{k!r}]')
            for k, v in value.items()
        }
    else:
        return value


def _get_value(obj, key):
    if isinstance(obj, Config):
        return obj._get_value(key)
    elif isinstance(obj, list):
        return obj[int(key)]
    elif isinstance(obj, tuple):
        return obj[int(key)]
    elif isinstance(obj, dict):
        return obj[key]
    else:
        raise ConfigError(f'Cannot get value of {obj} with key {key}')


def _set_value(obj, key, value, resolve_imports: bool = True):
    if isinstance(obj, Config):
        obj._set_value(key, value, resolve_imports=resolve_imports)
    elif isinstance(obj, list):
        index = int(key)
        default = obj[index] if 0 <= index < len(obj) else None
        obj[index] = _copy_value(_resolve_value(value, default, resolve_imports=resolve_imports))
    elif isinstance(obj, tuple):
        raise NotImplementedError('Overriding tuple values is not implemented')
    elif isinstance(obj, dict):
        default = obj.get(key) if isinstance(obj, dict) else None
        obj[key] = _copy_value(_resolve_value(value, default, resolve_imports=resolve_imports))
    else:
        raise ConfigError(f'Cannot set value of {obj} with key {key}')


def _get_creator_module() -> ModuleType | None:
    current_frame = inspect.currentframe()
    # current frame: this function
    # current frame back: place where this function is called from
    # current frame back back: place one level upperer
    assert current_frame is not None, 'Current frame is None. Do your python interpreter support frames?'
    assert current_frame.f_back is not None, 'Current frame back is None. Should not happen.'
    assert current_frame.f_back.f_back is not None, (
        'Current frame back back is None. This function was probably called from python interpreter.'
    )

    module = inspect.getmodule(current_frame.f_back.f_back)

    return module


class Config:
    def __init__(self, target, *args, **kwargs):
        """
        Initialize a Config object.

        Stores the callable target and its arguments and keyword arguments, which
        can be overridden/instantiated later.

        The args and kwargs could be strings with special syntax, which will be resolved to actual Python objects.
        "@path.to.object" will be resolved to the object similar to "from path.to import object".

        Relative imports (strings starting with '.') are only resolved during overrides when the
        default value is another Config instance. In all other contexts (including __init__),
        leading-dot strings are treated literally (e.g., '../data', './file', '.env').

        Args:
            target: The target object to be configured.
            *args: Positional arguments to be passed to the target object.
            **kwargs: Keyword arguments to be passed to the target object.

        Raises:
            AssertionError: If the target is not callable.

        Example:
            >>> @cfn.config()
            >>> def sum(a, b):
            >>>     return a + b
            >>> res = sum.override(a=1, b=2).instantiate()
            >>> assert res == 3

            >>> def sum(a, b):
            >>>     return a + b
            >>> res = cfn.Config(sum, a=1, b=2).instantiate()
            >>> assert res == 3

            >>> @cfn.config(status="@http.HTTPStatus.OK")
            >>> def return_status(status):
            >>>     return status
            >>> assert return_status() == http.HTTPStatus.OK
        """
        assert callable(target), f'Target must be callable, got object of type {type(target)}.'
        self.target = target
        # Copy Config/container args on store (mirroring _set_value) so a numeric dotted keyword
        # override in the same call (e.g. Config(Env, shared, **{'0.name': ...})) lands on a private
        # copy rather than mutating a shared positional value. See issue #31.
        self.args = [_copy_value(_resolve_value(arg)) for arg in args]
        self.kwargs = {}
        self._override_inplace(kwargs)

        self._creator_module = _get_creator_module()

    def override(self, **overrides) -> Config:
        """
        Create a new Config with updated parameters.

        This is the idiomatic way to derive named variants from one general config:
        define a single base ``Config`` and produce each variant with ``.override()``,
        rather than writing several near-duplicate config functions. Pass a dict of such
        variants to :func:`configuronic.cli` to expose them as CLI commands.

        Keys may be nested using dot notation to reach into sub-configs (e.g.
        ``"model.layers"``, ``"robot_arm.collision_coeff"``) and into list/dict slots
        (e.g. ``"cameras.left"``, ``"loaders.0"``).

        Values are resolved by type:
        - strings may use absolute imports (``@module.path.Object``) or relative
          imports (``.SiblingObject``);
        - concrete (non-``Config``) values — ints, floats, objects, ``Config`` instances,
          lists, dicts — pass straight through and replace the previous value.

        Because import strings are resolved, an override value is as trusted as your own
        code: it can name any importable object. When the values come from outside the
        process (a request, a URL, a user-supplied file), use :meth:`override_data`
        instead, which refuses import strings rather than resolving them.

        Note: overrides apply to an independent copy, so a variant never mutates the
        base — even for dotted overrides that reach through ``dict``/``list``/``tuple``
        containers (e.g. ``"cameras.left.fps"``), which are copied too. This also holds
        for ``Config`` (and container) values passed *as* overrides in the same call: a
        dotted key that descends into such a value (e.g. ``robot_arm=franka_sim`` together
        with ``"robot_arm.collision_coeff"``) lands on a private copy, never the shared
        instance.

        Args:
            **overrides: Parameter paths and their new values.

        Returns:
            Config: A new Config with overridden parameters.

        Raises:
            ConfigError: If parameter path is invalid.

        Example:
            >>> cfg = Config(Pipeline, model=Config(MyModel, layers=6))
            >>> new_cfg = cfg.override(**{'model.layers': 12})
            >>> new_cfg = cfg.override(model='@my_models.CustomModel')

            >>> # One general config, named variants via .override():
            >>> single_arm = cfn.Config(build, robot_arm=franka, gripper=robotiq)
            >>> droid = single_arm.override(robot_arm=franka_droid)
            >>> sim = single_arm.override(robot_arm=franka_sim, **{'robot_arm.collision_coeff': 2.0})
            >>> cfn.cli({'droid': droid, 'sim': sim})
        """
        overriden_cfg = self._copy()
        overriden_cfg._override_inplace(overrides)
        # we want to keep creator module (module override was called from) for the overriden config
        # But we override it after the overrides are applied, so that lists and dicts arguments
        # are resolved relative to the original config, not the overriden config.
        overriden_cfg._creator_module = _get_creator_module()

        return overriden_cfg

    def override_data(self, **overrides) -> Config:
        """
        Like :meth:`override`, but values are interpreted strictly as data.

        Use this when the override *values* come from outside the process — a network
        request, a URL query string, a user-supplied file. :meth:`override` treats a string
        starting with ``@`` or ``.`` as an object to import, which is right for overrides
        written by your own code but turns a config knob into arbitrary code execution when
        the value comes from a caller you do not control. ``override_data`` refuses those
        strings instead of resolving them, so an untrusted caller can tune arguments but
        never swap components.

        Both forms are refused, at any nesting depth (inside lists and dicts too):

        - absolute — ``'@os.system'``;
        - relative — ``'....os.system'``. The relative form is no safer than the absolute
          one: leading dots walk *up* the module tree from the current value's module, and
          enough of them leave the package entirely.

        Strings starting with ``@`` are refused whole, including the ``'@@x'`` escape that
        :meth:`override` reads as the literal ``'@x'``: a stored ``'@...'`` string is itself
        a valid base for a later relative override, so accepting one would let this caller
        choose the path a subsequent trusted override resolves against.

        Everything else behaves exactly like :meth:`override` — same dotted keys, same
        copy-on-write semantics, same treatment of values that are not import references
        (a leading-dot string with no config to resolve against, e.g. ``'./data'``, stays a
        literal string here just as it does there).

        Note this constrains values, not the caller: passing a ``Config`` (or any other
        Python object) as a value still works, since only your own code can do that. It is
        strings — the only thing external data can carry — that never become imports.

        Args:
            **overrides: Parameter paths and their new values.

        Returns:
            Config: A new Config with overridden parameters.

        Raises:
            ImportNotAllowedError: If a value (or a value nested in a list/dict) is an
                import reference. The offending key and value are on the exception, for
                reporting back to whoever supplied them.
            ConfigError: If a parameter path is invalid.

        Example:
            >>> params = {'codec.fps': 10}  # decoded from a request, a URL, a file
            >>> cfg = policy.override_data(**params)  # raises on {'codec': '@os.system'}
        """
        overriden_cfg = self._copy()
        overriden_cfg._override_inplace(overrides, resolve_imports=False)
        overriden_cfg._creator_module = _get_creator_module()

        return overriden_cfg

    def _override_inplace(self, overrides: dict[str, Any], resolve_imports: bool = True):
        for key, value in overrides.items():
            try:
                key_list = key.split('.')

                current_obj = self

                for i, part in enumerate(key_list[:-1]):
                    current_obj = _get_value(current_obj, part)
                    if current_obj is None:
                        path_to_not_found_arg = '.'.join(key_list[: i + 1])
                        raise ConfigError(f"Argument '{path_to_not_found_arg}' not found in config")

                _set_value(current_obj, key_list[-1], value, resolve_imports=resolve_imports)
            except ImportNotAllowedError as e:
                # Re-raise (rather than wrap) so callers can tell "you tried to sneak in an import"
                # apart from any other override failure. `e.key` holds the position inside the
                # value (for containers); the override key it belongs to is only known here.
                raise ImportNotAllowedError(f'{key}{e.key}', e.value) from None
            except Exception as e:
                raise ConfigError(f"Failed to override '{key}' with value '{value}'") from e

    def _set_value(self, key, value, resolve_imports: bool = True):
        default = self._get_value(key) if self._has_value(key) else None
        # Copy Config/container values on store (mirroring _copy_value for the base) so that a
        # dotted override descending into a value set in the same call lands on a private copy
        # rather than mutating a shared instance. See issue #31.
        value = _copy_value(_resolve_value(value, default, config=self, resolve_imports=resolve_imports))

        if key[0].isdigit():
            self.args[int(key)] = value
        else:
            self.kwargs[key] = value

    def _get_value(self, key):
        if key[0].isdigit():
            return self.args[int(key)]
        else:
            return self.kwargs.get(key)

    def _has_value(self, key):
        if key[0].isdigit():
            return int(key) < len(self.args)
        else:
            return key in self.kwargs

    def instantiate(self) -> Any:
        """
        Instatiate the target function with the given arguments and keyword arguments.

        Instantiation semantics: a config is a closure, and every referenced ``Config``
        is built independently — there is no caching. Referencing the same sub-config
        from two places produces two separate objects. To let several components share
        one object, bind them together: take that object as a single argument and build
        the dependents from it, rather than pointing several slots at the same
        sub-config.

        Returns:
            The instantiated target function.

        Raises:
            ConfigError: If the target function cannot be instantiated.
        """
        return self._instantiate_internal()

    def _instantiate_internal(self, path: str = ''):
        """
        Instatiate the target function with the given arguments and keyword arguments.

        Args:
            path (str): The path to the current key. Used for error reporting.

        Returns:
            The instantiated target function.

        Raises:
        """

        def _instantiate_value(value, key, path):
            try:
                if isinstance(value, Config):
                    return value._instantiate_internal(path + f'{key}.')
                elif isinstance(value, list | tuple):
                    return type(value)(_instantiate_value(item, f'{key}[{i}]', path) for i, item in enumerate(value))
                elif isinstance(value, dict):
                    return {k: _instantiate_value(v, f'{key}["{k}"]', path) for k, v in value.items()}
                else:
                    return value
            except Exception as e:
                if isinstance(e, ConfigError):
                    raise e
                else:
                    raise ConfigError(f'Error instantiating "{path}{key}": {e}') from e

        # Recursively instantiate any Config objects in args
        instantiated_args = [_instantiate_value(arg, key, path) for key, arg in enumerate(self.args)]

        # Recursively instantiate any Config objects in kwargs
        instantiated_kwargs = {key: _instantiate_value(value, key, path) for key, value in self.kwargs.items()}

        return self.target(*instantiated_args, **instantiated_kwargs)

    def _to_dict(self) -> dict[str, Any]:
        res = {}

        res['@target'] = f'{INSTANTIATE_PREFIX}{self.target.__module__}.{self.target.__name__}'
        args = [_to_dict(arg) for arg in self.args]
        if len(args) > 0:
            res['*args'] = args
        kwargs = {key: _to_dict(value) for key, value in self.kwargs.items()}
        if len(kwargs) > 0:
            res.update(kwargs)
        return res

    def __str__(self):
        return yaml.dump(self._to_dict(), default_flow_style=None, sort_keys=False, width=140)

    def copy(self) -> Config:
        """
        Recursively copy config signatures.
        """

        cfg = self._copy()
        cfg._creator_module = _get_creator_module()
        return cfg

    def _copy(self):
        """
        Recursively copy config signatures.
        """

        new_args = [_copy_value(arg) for arg in self.args]

        new_kwargs = {key: _copy_value(value) for key, value in self.kwargs.items()}

        cfg = Config(self.target)
        cfg.args = new_args
        cfg.kwargs = new_kwargs
        cfg._creator_module = self._creator_module
        return cfg

    def __call__(self, **kwargs):
        """
        Override the config with the given kwargs and instantiate the config.

        Useful for creating a function for a CLI.

        Args:
            **kwargs: Keyword arguments to override the config.

        Returns:
            The instantiated config.

        Example:
            >>> import fire
            >>> @cfn.config()
            >>> def sum(a, b):
            >>>     return a + b
            >>> option1 = sum.override(a=1)
            >>> option2 = sum.override(b=2)
            >>> fire.Fire()
            >>> # Shell call: python script.py option1 --b 5
            >>> # Shell call: python script.py option2 --a 5
        """
        return self.override(**kwargs).instantiate()


def config(**kwargs) -> Callable[[Callable], Config]:
    """
    Decorator to create a Config object.

    Args:
        **kwargs: Keyword arguments to be passed to the target object.

    Returns:
        A decorator factory that creates a Config object.

    Example:
        >>> @cfn.config(a=1, b=2)
        >>> def sum(a, b):
        >>>     return a + b
        >>> res = sum.instantiate()
        >>> assert res == 3

        >>> @cfn.config()
        >>> def sum(a, b):
        >>>     return a + b
        >>> res = sum.override(a=1, b=2).instantiate()
        >>> assert res == 3
    """

    def _config_decorator(target):
        config = Config(target, **kwargs)
        config._creator_module = _get_creator_module()
        return config

    return _config_decorator
