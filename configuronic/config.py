from __future__ import annotations

import functools
import importlib
import inspect
import posixpath
from collections import deque
from collections.abc import Callable
from types import ModuleType, UnionType
from typing import Any, ForwardRef, NamedTuple, Union, get_args, get_origin

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


_UNRESOLVED = object()


def _annotation_namespaces(target: Any) -> list[dict[str, Any]]:
    """Namespaces a stringified annotation of `target` may have been written in.

    An annotation has to be resolved where it was written, so follow the same hops
    :func:`inspect.signature` takes to find the parameters: through ``functools.partial``
    and ``functools.wraps`` wrappers, whose own module knows nothing about the wrapped
    function's names — stopping, as it does, at a callable that declares its own
    ``__signature__``, since the parameters then come from the wrapper rather than from
    what it wraps. For a class, the reported parameters come from a metaclass
    ``__call__``, from ``__new__`` or from ``__init__``, chosen by rules that vary across
    Python versions — so offer all three, most specific first, and let the caller take
    the first that resolves. Callable objects keep no globals of their own and fall back
    to the module their class came from.
    """
    func = target
    # `inspect.unwrap` guards against a circular `__wrapped__` chain and so does the
    # `__signature__` stop below, but a loop that never ends would hang `instantiate()`.
    seen: set[int] = set()
    while id(func) not in seen:
        seen.add(id(func))
        if hasattr(func, '__signature__'):
            break
        elif isinstance(func, functools.partial):
            func = func.func
        elif hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        else:
            break

    sources = [type(func).__call__, func.__new__, func.__init__] if inspect.isclass(func) else [func]

    namespaces: list[dict[str, Any]] = []
    for source in sources:
        namespace = getattr(source, '__globals__', None)
        if namespace is None:
            namespace = getattr(inspect.getmodule(source), '__dict__', None)
        if namespace and not any(namespace is known for known in namespaces):
            namespaces.append(namespace)
    return namespaces


def _resolve_string_annotation(annotation: str, target: Any) -> Any:
    """Evaluate a stringified annotation, or return `_UNRESOLVED` if no namespace can."""
    for namespace in _annotation_namespaces(target):
        try:
            return eval(annotation, namespace)
        except Exception:
            continue
    return _UNRESOLVED


def _is_config_annotation(annotation: Any, target: Any, _resolved_text: frozenset[str] = frozenset()) -> bool:
    """Does this parameter annotation ask for the `Config` itself?

    True for a bare :class:`Config` and for a union that contains it (``Config | None``),
    in either case optionally wrapped in ``Annotated``. Containers of configs
    (``list[Config]``) are deliberately excluded: only a whole argument can be handed
    over unresolved, not selected items inside one.

    ``_resolved_text`` carries the annotation strings already resolved on the way here, so
    that names defined in terms of each other cannot loop.
    """
    if annotation is inspect.Parameter.empty:
        return False

    # Under `from __future__ import annotations` (or when the annotation is quoted) we get
    # source text such as 'cfn.Config'. Evaluate it where it was written — what
    # `typing.get_type_hints` does, but one parameter at a time, so an unresolvable forward
    # reference on an unrelated parameter cannot hide a perfectly good annotation here. The
    # decision is then made on the object, so every spelling works, including an alias
    # (`from configuronic import Config as C`).
    #
    # Resolving can yield another string: a quoted annotation in a module that also
    # postpones evaluation is stored as the *source text* of the quoted expression, so
    # `pipeline: 'cfn.Config'` arrives as "'cfn.Config'". Keep going until it is not a
    # string any more — but never revisit one, since module-level names can be defined in
    # terms of each other (`A = 'B'`, `B = 'A'`), and no cycle of them is a Config.
    while isinstance(annotation, ForwardRef | str):
        text = annotation.__forward_arg__ if isinstance(annotation, ForwardRef) else annotation
        if text in _resolved_text:
            return False
        _resolved_text = _resolved_text | {text}
        annotation = _resolve_string_annotation(text, target)
        if annotation is _UNRESOLVED:
            return False

    if hasattr(annotation, '__metadata__'):  # Annotated[Config, ...]
        return _is_config_annotation(annotation.__origin__, target, _resolved_text)

    if annotation is Config:
        return True

    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        return any(_is_config_annotation(arg, target, _resolved_text) for arg in get_args(annotation))

    return False


class _LazyDeclaration(NamedTuple):
    """Which of a target's parameters ask for the `Config` itself, by position and by name.

    ``positional``/``keywords`` cover the named parameters; ``var_positional``/``var_keyword``
    apply to anything beyond them, i.e. what ``*args`` / ``**kwargs`` would collect.
    """

    positional: tuple[bool, ...]
    keywords: dict[str, bool]
    var_positional: bool
    var_keyword: bool


def _read_lazy_declaration(target: Any) -> _LazyDeclaration:
    """Read `target`'s signature and mark the parameters annotated `Config`."""
    try:
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):
        # Builtins and other C callables often have no introspectable signature. Then
        # nothing is annotated, so nothing is lazy.
        return _LazyDeclaration((), {}, False, False)

    positional: list[bool] = []
    keywords: dict[str, bool] = {}
    var_positional = var_keyword = False
    for name, param in parameters.items():
        is_lazy = _is_config_annotation(param.annotation, target)
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            var_positional = is_lazy
        elif param.kind is inspect.Parameter.VAR_KEYWORD:
            var_keyword = is_lazy
        else:
            if param.kind is not inspect.Parameter.KEYWORD_ONLY:
                positional.append(is_lazy)
            if param.kind is not inspect.Parameter.POSITIONAL_ONLY:
                keywords[name] = is_lazy
    return _LazyDeclaration(tuple(positional), keywords, var_positional, var_keyword)


# Reading the declaration means inspecting a signature and resolving annotations, which is
# an order of magnitude more expensive than instantiating a small config. It depends on the
# target alone, so cache it rather than paying it on every instantiate().
_lazy_declaration = functools.lru_cache(maxsize=1024)(_read_lazy_declaration)


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

    def _lazy_slots(self) -> tuple[set[int], set[str]]:
        """Argument slots the target wants handed over unresolved.

        A parameter annotated :class:`Config` (or ``Config | None``) declares that the
        target wants the config object itself rather than what it builds — because it
        instantiates it later, more than once, or with overrides it only learns at runtime.
        Returns the positional indices and keyword names whose stored values
        :meth:`_instantiate_internal` must pass through as they are.

        Whether a target wants a config or an object is a property of the target, so the
        declaration lives in its signature: callers keep writing ordinary values and
        ordinary overrides.
        """
        try:
            declaration = _lazy_declaration(self.target)
        except TypeError:
            # An unhashable callable (a target instance whose class sets __hash__ = None)
            # cannot be a cache key. Read its declaration directly.
            declaration = _read_lazy_declaration(self.target)

        positional = declaration.positional
        lazy_args = {
            i for i in range(len(self.args)) if (positional[i] if i < len(positional) else declaration.var_positional)
        }
        lazy_kwargs = {key for key in self.kwargs if declaration.keywords.get(key, declaration.var_keyword)}
        return lazy_args, lazy_kwargs

    def instantiate(self) -> Any:
        """
        Instatiate the target function with the given arguments and keyword arguments.

        Instantiation semantics: a config is a closure, and every referenced ``Config``
        is built independently — there is no caching. Referencing the same sub-config
        from two places produces two separate objects. To let several components share
        one object, bind them together: take that object as a single argument and build
        the dependents from it, rather than pointing several slots at the same
        sub-config.

        A target can opt out of resolution for a particular argument by annotating that
        parameter :class:`Config`: it then receives the stored config itself, not what it
        builds. That is for targets that need to build it later, more than once, or with
        overrides they only learn at runtime — a server applying per-request overrides,
        for instance. Everything else about the argument is unchanged: it is an ordinary
        config, so ``.override()`` (including dotted keys reaching into it) and ``--help``
        keep working.

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

        # Slots the target asked for unresolved, by annotating the parameter `Config`.
        lazy_args, lazy_kwargs = self._lazy_slots()

        # Recursively instantiate any Config objects in args
        instantiated_args = [
            arg if key in lazy_args else _instantiate_value(arg, key, path) for key, arg in enumerate(self.args)
        ]

        # Recursively instantiate any Config objects in kwargs
        instantiated_kwargs = {
            key: value if key in lazy_kwargs else _instantiate_value(value, key, path)
            for key, value in self.kwargs.items()
        }

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
