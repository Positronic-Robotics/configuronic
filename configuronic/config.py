from __future__ import annotations

import functools
import importlib
import inspect
import posixpath
import sys
from collections import deque
from collections.abc import Callable, Mapping
from types import ModuleType, UnionType
from typing import Annotated, Any, ForwardRef, NamedTuple, TypeVar, Union, get_args, get_origin

import yaml

try:  # `type X = ...` aliases (PEP 695), Python 3.12+
    from typing import TypeAliasType
except ImportError:  # pragma: no cover - exercised on 3.10 and 3.11
    TypeAliasType = None

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


def _partial_method_of(func: Any) -> functools.partialmethod | None:
    """The `functools.partialmethod` behind an unbound accessor, if this is one.

    Reaching a ``partialmethod`` through its class hands back a plain function generated
    inside ``functools``, which keeps a reference to the real method — under
    ``_partialmethod`` up to 3.12 and ``__partialmethod__`` from 3.13. Whichever name it
    carries, that reference is where its parameters, and their annotations, come from.
    """
    for attribute in ('__partialmethod__', '_partialmethod'):
        candidate = getattr(func, attribute, None)
        if isinstance(candidate, functools.partialmethod):
            return candidate
    return None


def _unwrap_signature_source(func: Any) -> Any:
    """Follow the hops :func:`inspect.signature` takes from a callable to its parameters.

    Through ``functools.partial`` and ``functools.wraps`` wrappers and the function a
    ``functools.partialmethod`` generates, none of whose modules know anything about the
    wrapped function's names — stopping, as it does, at a callable that declares its own
    ``__signature__``, since the parameters then come from the wrapper rather than from
    what it wraps.
    """
    # `inspect.unwrap` guards against a circular `__wrapped__` chain and so does the
    # `__signature__` stop below, but a loop that never ends would hang `instantiate()`.
    # The objects are held, not just their ids: a hop can mint a transient (a bound method,
    # a partial built by a property), and a freed id is reused straight away — the loop
    # would then stop at a callable it has never actually seen.
    seen: list[Any] = []
    while not any(func is visited for visited in seen):
        seen.append(func)
        if hasattr(func, '__signature__'):
            break
        elif isinstance(func, functools.partial):
            func = func.func
        elif (partial_method := _partial_method_of(func)) is not None:
            func = partial_method.func
        elif hasattr(func, '__wrapped__'):
            func = func.__wrapped__
        else:
            break
    return func


class _AnnotationSource(NamedTuple):
    """A namespace an annotation may have been written in, and what its callable declares.

    ``localns`` is the body of the class the callable was defined in, if any: a name bound
    there is in scope for an annotation written there, which is how the same annotation
    resolves in a module that does *not* postpone evaluation.
    """

    globalns: dict[str, Any]
    localns: Mapping[str, Any]
    parameters: dict[str, inspect.Parameter]


def _declared_parameters(func: Any) -> dict[str, inspect.Parameter]:
    try:
        return dict(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return {}


def _defining_class(cls: type, method: str) -> type | None:
    """The class in `cls`'s MRO whose body defines `method` — where its annotations live."""
    for klass in inspect.getmro(cls):
        if method in vars(klass):
            return klass
    return None


def _owning_class(func: Any) -> type | None:
    """The class body `func` was written in, for a function that carries no binding.

    A bound method names what it is bound to, but a static method — or any function
    reached through the class that defines it — is a plain function, and only its
    qualified name says where it was written.
    """
    qualname = getattr(func, '__qualname__', '')
    globalns = getattr(func, '__globals__', None)
    if globalns is None or '.' not in qualname:
        return None

    owner: Any = globalns
    for part in qualname.split('.')[:-1]:
        if part == '<locals>':
            return None  # defined inside a function: that scope is gone, nothing to recover
        try:
            owner = owner[part] if owner is globalns else getattr(owner, part)
        except (KeyError, AttributeError):
            return None
    return owner if inspect.isclass(owner) else None


def _annotation_sources(target: Any) -> list[_AnnotationSource]:
    """Where a stringified annotation of `target` may have been written.

    An annotation has to be resolved where it was written, so follow the target to the
    callable that declares the parameters. For a class, the reported parameters come from
    a metaclass ``__call__``, from ``__new__`` or from ``__init__``, by rules that depend
    on which of them the class defines itself — so offer all three, most specific first,
    along with what each declares, and let :func:`_sources_for` pick. Each can be
    decorated in turn, so each is followed the same way. For a callable object the
    parameters come from its class' ``__call__``, which may be inherited from a base in
    another module; the object itself keeps no globals and falls back to the module its
    own class came from.
    """
    func = _unwrap_signature_source(target)
    if inspect.isclass(func):
        # Each candidate is paired with the class body it was written in — the one that
        # defines it, which for an inherited method is a base rather than `func` itself.
        candidates = [
            (type(func).__call__, _defining_class(type(func), '__call__')),
            (func.__new__, _defining_class(func, '__new__')),
            (func.__init__, _defining_class(func, '__init__')),
        ]
    else:
        # A method was written in a class body too. A bound one names what it is bound to;
        # a static method (or any function reached through its class) has only its
        # qualified name to say where it came from.
        bound_to = getattr(func, '__self__', None)
        owner = bound_to if inspect.isclass(bound_to) else type(bound_to) if bound_to is not None else None
        written_in = _defining_class(owner, getattr(func, '__name__', '')) if owner is not None else None
        written_in = written_in if written_in is not None else _owning_class(func)
        candidates = [(type(func).__call__, _defining_class(type(func), '__call__')), (func, written_in)]

    sources: list[_AnnotationSource] = []
    seen: list[tuple[dict[str, Any], type | None]] = []
    for candidate, defined_in in candidates:
        candidate = _unwrap_signature_source(candidate)
        globalns = getattr(candidate, '__globals__', None)
        if globalns is None:
            globalns = getattr(inspect.getmodule(candidate), '__dict__', None)
        if not globalns:
            continue
        # Compare on what the namespaces are *taken from*: `vars()` hands back a new
        # mappingproxy every call, so comparing the mappings by identity never matches.
        if any(globalns is known_globals and defined_in is known_class for known_globals, known_class in seen):
            continue
        seen.append((globalns, defined_in))
        localns: Mapping[str, Any] = vars(defined_in) if defined_in is not None else {}
        sources.append(_AnnotationSource(globalns, localns, _declared_parameters(candidate)))
    return sources


def _same_annotation(declared: Any, reported: Any) -> bool:
    """Is this the same annotation, without running whatever `__eq__` it may define?

    An annotation is any object, and comparing two of them can execute arbitrary code — or
    return something that is not a boolean — while we are only reading a signature. The
    annotation object itself is carried through to the reported parameter, so identity
    answers this; the string form gets a real comparison because it is the one case where
    equal-but-distinct objects are plausible, and comparing two strings is safe.
    """
    if declared is reported:
        return True
    return isinstance(declared, str) and isinstance(reported, str) and declared == reported


def _sources_for(sources: list[_AnnotationSource], param: inspect.Parameter) -> list[_AnnotationSource]:
    """Where this parameter's annotation may be resolved, most likely first.

    Only one of the candidates wrote this parameter, so the first that declares it — same
    name, same annotation, candidates being ordered most specific first — is the one whose
    namespace applies, and a name it cannot resolve is unresolved rather than something a
    sibling namespace happens to define. Two candidates declaring the identical parameter
    is not a reason to consult both: only the first can be the one the signature came from.
    When none of them declares it (a callable with an explicit ``__signature__``, say)
    there is nothing to go on, so offer them all.
    """
    for source in sources:
        declared = source.parameters.get(param.name)
        if declared is not None and _same_annotation(declared.annotation, param.annotation):
            return [source]
    return sources


def _module_source(module: Any) -> list[_AnnotationSource]:
    """The namespace of the module a `ForwardRef` names, if it names one.

    The attribute holds whatever was handed to `ForwardRef` — the module, or its name,
    which is what `typing.get_type_hints` looks up in `sys.modules`.
    """
    if isinstance(module, str):
        module = sys.modules.get(module)
    namespace = getattr(module, '__dict__', None)
    return [_AnnotationSource(namespace, {}, {})] if namespace else []


def _resolve_string_annotation(annotation: str, sources: list[_AnnotationSource]) -> Any:
    """Evaluate a stringified annotation, or return `_UNRESOLVED` if no namespace can."""
    for source in sources:
        try:
            return eval(annotation, source.globalns, source.localns)
        except Exception:
            continue
    return _UNRESOLVED


def _type_alias(annotation: Any) -> Any | None:
    """The `type` alias (PEP 695) this annotation stands for, if it stands for one.

    An alias used bare (``Deferred``) is the alias object itself; one used with arguments
    (``Deferred[Config]``) is a generic alias over it, and what it stands for is only
    reachable through the alias it wraps.
    """
    if TypeAliasType is None:
        return None
    if isinstance(annotation, TypeAliasType):
        return annotation
    origin = get_origin(annotation)
    return origin if isinstance(origin, TypeAliasType) else None


def _is_config_annotation(
    annotation: Any,
    sources: list[_AnnotationSource],
    _seen: frozenset[str | int] = frozenset(),
    _bound: Mapping[Any, Any] | None = None,
) -> bool:
    """Does this parameter annotation ask for the `Config` itself?

    True for a bare :class:`Config` and for a union that contains it (``Config | None``),
    in either case optionally wrapped in ``Annotated`` or reached through a ``type`` alias.
    Containers of configs (``list[Config]``) are deliberately excluded: only a whole
    argument can be handed over unresolved, not selected items inside one.

    ``sources`` are where a stringified annotation may be resolved, from
    :func:`_sources_for`. ``_seen`` carries what has already been followed on the way here
    — annotation strings, and the identities of ``type`` aliases and type parameters —
    because any of them can be written in terms of itself, and nothing that comes round
    again is a ``Config``. ``_bound`` carries what the arguments of a specialized alias
    (``Deferred[Config]``) bind its type parameters to, so a parameter met inside the
    alias' value stands for what was passed for it.
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
    #
    # A `type X = ...` alias (PEP 695) hides what it stands for behind `__value__`, which is
    # evaluated on access and may be the alias itself, so it is followed the same way. Given
    # arguments (`type Deferred[T] = T | None` used as `Deferred[Config]`), what its value is
    # written in terms of are its type parameters, so those are followed too.
    _bound = _bound if _bound is not None else {}
    while True:
        if isinstance(annotation, ForwardRef | str):
            text = annotation.__forward_arg__ if isinstance(annotation, ForwardRef) else annotation
            if text in _seen:
                return False
            _seen = _seen | {text}
            # A `ForwardRef` may name the module it was written in, which is then where it
            # is resolved — `typing.get_type_hints` honours that, and so does this.
            declared_in = getattr(annotation, '__forward_module__', None) if annotation is not text else None
            annotation = _resolve_string_annotation(text, _module_source(declared_in) + sources)
            if annotation is _UNRESOLVED:
                return False
        elif (alias := _type_alias(annotation)) is not None:
            if id(alias) in _seen:
                return False
            _seen = _seen | {id(alias)}
            _bound = {**_bound, **dict(zip(alias.__type_params__, get_args(annotation), strict=False))}
            try:
                annotation = alias.__value__
            except Exception:
                return False
        elif isinstance(annotation, TypeVar) and annotation in _bound:
            if id(annotation) in _seen:
                return False
            _seen = _seen | {id(annotation)}
            annotation = _bound[annotation]
        else:
            break

    # An annotation can be any object, so ask typing what this one is rather than reading
    # attributes off it: something unrelated carrying a `__metadata__` is not `Annotated`.
    origin = get_origin(annotation)

    if origin is Annotated:  # Annotated[Config, ...]
        return _is_config_annotation(annotation.__origin__, sources, _seen, _bound)

    if annotation is Config:
        return True

    if origin is Union or origin is UnionType:
        return any(_is_config_annotation(arg, sources, _seen, _bound) for arg in get_args(annotation))

    return False


class _LazyDeclaration:
    """Which of a target's parameters ask for the `Config` itself, answered on demand.

    A parameter's annotation is only resolved when a config actually supplies that
    parameter. Resolving one means evaluating whatever expression was written there, which
    can import a module or run code of its own, and a config has no business causing that
    for parameters it never sets. Answers are remembered, so each parameter costs that at
    most once per target.

    Reading a signature must never be what breaks `instantiate()`: a target free to define
    `__signature__`, `__getattr__` or `__class__` however it likes can make introspection
    raise anything at all, and a parameter we cannot classify is simply not a `Config`
    parameter.
    """

    __slots__ = ('_answered', '_keywords', '_positional', '_sources', '_target', '_var_keyword', '_var_positional')

    def __init__(self, target: Any):
        self._target = target
        self._sources: list[_AnnotationSource] | None = None
        self._answered: dict[str, bool] = {}
        self._positional: list[inspect.Parameter] = []
        self._keywords: dict[str, inspect.Parameter] = {}
        self._var_positional: inspect.Parameter | None = None
        self._var_keyword: inspect.Parameter | None = None

        try:
            parameters = inspect.signature(target).parameters
        except Exception:
            # Builtins and other C callables often have no introspectable signature; an
            # exotic one can raise anything. Then nothing is classified, so nothing is lazy.
            return

        for name, param in parameters.items():
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                self._var_positional = param
            elif param.kind is inspect.Parameter.VAR_KEYWORD:
                self._var_keyword = param
            else:
                if param.kind is not inspect.Parameter.KEYWORD_ONLY:
                    self._positional.append(param)
                if param.kind is not inspect.Parameter.POSITIONAL_ONLY:
                    self._keywords[name] = param

    def positional(self, index: int) -> bool:
        """Does the parameter filled by positional argument `index` want the config?"""
        if index < len(self._positional):
            return self._wants_config(self._positional[index])
        return self._var_positional is not None and self._wants_config(self._var_positional)

    def keyword(self, name: str) -> bool:
        """Does the parameter named `name` — or the `**kwargs` collecting it — want it?"""
        param = self._keywords.get(name, self._var_keyword)
        return param is not None and self._wants_config(param)

    def _wants_config(self, param: inspect.Parameter) -> bool:
        answer = self._answered.get(param.name)
        if answer is None:
            try:
                if self._sources is None:
                    self._sources = _annotation_sources(self._target)
                answer = _is_config_annotation(param.annotation, _sources_for(self._sources, param))
            except Exception:
                answer = False
            self._answered[param.name] = answer
        return answer


class _TargetKey:
    """Cache key that compares targets by identity.

    `lru_cache` keys by ``__hash__``/``__eq__``, and a callable object may define either:
    two targets that compare equal can still report different signatures (a per-instance
    ``__signature__``, say), and sharing one declaration between them would hand the wrong
    arguments over unresolved. Keying by identity also means a target that cannot be hashed
    at all is no special case; holding the target here keeps its id from being reused.
    """

    __slots__ = ('target',)

    def __init__(self, target: Any):
        self.target = target

    def __hash__(self) -> int:
        return id(self.target)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _TargetKey) and other.target is self.target


# Reading the declaration means inspecting a signature and resolving annotations, which is
# an order of magnitude more expensive than instantiating a small config. It depends on the
# target alone, so cache it rather than paying it on every instantiate(). A target's
# signature is read once and taken as settled: rewriting a live function's __annotations__
# after a config has instantiated it is not observed, and checking for that would mean
# re-reading the signature every time, which is the cost the cache exists to avoid.
@functools.lru_cache(maxsize=1024)
def _lazy_declaration(key: _TargetKey) -> _LazyDeclaration:
    return _LazyDeclaration(key.target)


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

    def override(self, /, **overrides) -> Config:
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

    def override_data(self, /, **overrides) -> Config:
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
        declaration = _lazy_declaration(_TargetKey(self.target))

        lazy_args = {i for i in range(len(self.args)) if declaration.positional(i)}
        lazy_kwargs = {key for key in self.kwargs if declaration.keyword(key)}
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

        Such an argument is the one thing here that is *not* built afresh: the target is
        handed the config held in that slot, the same object on every call, so treat it as
        read-only and derive from it with ``.override()`` / ``.override_data()``, which
        copy. That is deliberate — the config is what the target asked for, and copying it
        on the way past would only be undone by the first override the target applies.

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

    def __call__(self, /, **kwargs):
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
