"""Reading a target's signature to find the parameters that ask for a config itself.

A parameter annotated with a marker class — :class:`configuronic.Config` — declares that
the target wants that object rather than what it builds. Answering "is this annotation the
marker?" is the whole job of this module, and it is harder than it looks: an annotation may
be source text (``from __future__ import annotations``), a name bound only in the class
body it was written in, a forward reference naming its own module, or a ``type`` alias
standing for something else entirely.

Two rules shape everything here.

**Resolve an annotation only in the namespace that wrote it.** A stringified annotation is
just text, and the same text means different things in different modules. So the target is
followed to the callable that actually declares the parameter — through ``functools``
wrappers, to the class body a method was written in, to the base a method was inherited
from — and the annotation is resolved there, not wherever it is convenient. A name that
does not resolve where it was written is unresolved, not something a sibling namespace
happens to define.

**Never fail, and never run user code to find out.** Classifying a parameter is something
a config does on its way to calling the target, so it must not be what breaks the call. An
annotation can be any object at all, with a hostile ``__eq__`` or ``__getattribute__``; a
target can define ``__signature__`` as a property that raises. Anything that goes wrong
while classifying means "not a marker annotation", never an exception. Annotations are also
resolved one parameter at a time, and only for parameters a config actually supplies, so
evaluating an unrelated annotation cannot import a module or raise on a caller's behalf.

Both rules are why this is not :func:`typing.get_type_hints`, which resolves every
parameter at once, raises on a name it cannot resolve, and does not see class-body scope.
"""

from __future__ import annotations

import functools
import inspect
import sys
from collections.abc import Callable, Mapping
from types import MappingProxyType, UnionType
from typing import Annotated, Any, ForwardRef, NamedTuple, TypeVar, Union, get_args, get_origin

try:  # `type X = ...` aliases (PEP 695), Python 3.12+
    from typing import TypeAliasType
except ImportError:  # pragma: no cover - exercised on 3.10 and 3.11
    TypeAliasType = None

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


def _signature_chain(func: Any) -> list[Any]:
    """Every callable :func:`inspect.signature` passes through on its way to the parameters.

    Through ``functools.partial`` and ``functools.wraps`` wrappers and the function a
    ``functools.partialmethod`` generates, none of whose modules know anything about the
    wrapped function's names — stopping, as it does, at a callable that declares its own
    ``__signature__``, since the parameters then come from the wrapper rather than from
    what it wraps. The last link is where the parameters come from; the ones before it
    still hold what the target was when it was handed over, such as a binding to an
    instance that the function it decorates knows nothing about.
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
    return seen


def _unwrap_signature_source(func: Any) -> Any:
    """The callable at the end of the chain — the one that declares the parameters."""
    return _signature_chain(func)[-1]


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


def _class_namespace(cls: type) -> Mapping[str, Any]:
    """The body of `cls` as a scope, under the spellings an annotation there would use.

    A name beginning with two underscores is mangled where it is written — ``__Alias`` in
    the body of ``Factory`` is stored as ``_Factory__Alias`` — while a postponed
    annotation keeps the source text, so resolving it needs the name as written. Mangling
    is by the class the body belongs to, with the leading underscores of its own name
    dropped, and a class named only of underscores mangles nothing.
    """
    stripped = cls.__name__.lstrip('_')
    if not stripped:
        return vars(cls)

    namespace = dict(vars(cls))
    prefix = f'_{stripped}__'
    for name, value in vars(cls).items():
        if name.startswith(prefix):
            namespace[f'__{name[len(prefix) :]}'] = value
    return namespace


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
    a declared ``__signature__``, from a metaclass ``__call__``, from ``__new__`` or from
    ``__init__``, by rules that depend on which of them the class defines itself — so
    offer them all, most specific first, along with what each declares, and let
    :func:`_sources_for` pick. Each can be decorated in turn, so each is followed the same
    way. For a callable object the parameters come from its class' ``__call__``, which may
    be inherited from a base in another module; the object itself keeps no globals and
    falls back to the module its own class came from.
    """
    chain = _signature_chain(target)
    func = chain[-1]
    if inspect.isclass(func):
        # Each candidate is paired with the class body it was written in — the one that
        # defines it, which for an inherited method is a base rather than `func` itself.
        candidates = [
            (type(func).__call__, _defining_class(type(func), '__call__')),
            (func.__new__, _defining_class(func, '__new__')),
            (func.__init__, _defining_class(func, '__init__')),
        ]
        # A declared signature outranks all three: it is what `inspect.signature` reports.
        # Being a statement in a class body, the body that binds `__signature__` is where
        # its annotations were written — the class' own body, or its metaclass', which is
        # where the attribute is found when the class itself does not define one. Only a
        # real `Signature` counts, since that is the test `inspect.signature` itself
        # applies: `__signature__ = None` means the parameters come from the constructor
        # after all, and answering for them here would be answering in the wrong body.
        if isinstance(getattr(func, '__signature__', None), inspect.Signature):
            declared_in = _defining_class(func, '__signature__')
            declared_in = declared_in if declared_in is not None else _defining_class(type(func), '__signature__')
            if declared_in is not None:
                candidates.insert(0, (func, declared_in))
    else:
        # A method was written in a class body too. A bound one names what it is bound to;
        # a static method (or any function reached through its class) has only its
        # qualified name to say where it came from. The binding can sit anywhere in the
        # chain rather than at its end — a decorated bound method leads through
        # `__wrapped__` to the undecorated function, which knows nothing of the instance —
        # so it is looked for from the target inwards.
        bound_to = next((link.__self__ for link in chain if hasattr(link, '__self__')), None)
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
            # No globals of its own (a class, a C callable), so the enclosing scope is the
            # module of the body it was written in — which is not the candidate's own
            # module when that body belongs to a base or to a metaclass.
            globalns = getattr(inspect.getmodule(defined_in if defined_in is not None else candidate), '__dict__', None)
        if not globalns:
            continue
        # Compare on what the namespaces are *taken from*: `vars()` hands back a new
        # mappingproxy every call, so comparing the mappings by identity never matches.
        if any(globalns is known_globals and defined_in is known_class for known_globals, known_class in seen):
            continue
        seen.append((globalns, defined_in))
        localns: Mapping[str, Any] = _class_namespace(defined_in) if defined_in is not None else {}
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


class _Resolution(NamedTuple):
    """Following one annotation to whatever it finally stands for.

    ``marker`` is the class a parameter asks for by being annotated with it. ``sources``
    are the namespaces a stringified annotation may be resolved in, from
    :func:`_sources_for`. ``followed`` carries what has already been followed on the way
    here — annotation strings, and the identities of ``type`` aliases and type parameters
    — because any of them can be written in terms of itself, and nothing that comes round
    again is the marker. ``bound`` carries what the arguments of a specialized alias
    (``Deferred[Config]``) bind its type parameters to, so a parameter met inside the
    alias' value stands for what was passed for it.
    """

    marker: type
    sources: list[_AnnotationSource]
    followed: frozenset[str | int] = frozenset()
    bound: Mapping[Any, Any] = MappingProxyType({})

    def following(self, step: str | int, binding: Any = ()) -> _Resolution:
        """The same resolution, one step further along, with any type parameters bound."""
        return self._replace(followed=self.followed | {step}, bound={**self.bound, **dict(binding)})

    def wants_marker(self, annotation: Any) -> bool:
        """Does this annotation ask for the marker itself?

        True for the bare marker and for a union that contains it (``Config | None``), in
        either case optionally wrapped in ``Annotated`` or reached through a ``type``
        alias. Containers of configs (``list[Config]``) are deliberately excluded: only a
        whole argument can be handed over unresolved, not selected items inside one.
        """
        if annotation is inspect.Parameter.empty:
            return False

        # Under `from __future__ import annotations` (or when the annotation is quoted) we
        # get source text such as 'cfn.Config'. Evaluate it where it was written — what
        # `typing.get_type_hints` does, but one parameter at a time, so an unresolvable
        # forward reference on an unrelated parameter cannot hide a perfectly good
        # annotation here. The decision is then made on the object, so every spelling
        # works, including an alias (`from configuronic import Config as C`).
        #
        # Resolving can yield another string: a quoted annotation in a module that also
        # postpones evaluation is stored as the *source text* of the quoted expression, so
        # `pipeline: 'cfn.Config'` arrives as "'cfn.Config'". Keep going until it is not a
        # string any more — but never revisit one, since module-level names can be defined
        # in terms of each other (`A = 'B'`, `B = 'A'`), and no cycle of them is a Config.
        #
        # A `type X = ...` alias (PEP 695) hides what it stands for behind `__value__`,
        # which is evaluated on access and may be the alias itself, so it is followed the
        # same way. Given arguments (`type Deferred[T] = T | None` used as
        # `Deferred[Config]`), what its value is written in terms of are its type
        # parameters, so those are followed too.
        state = self
        while True:
            if isinstance(annotation, ForwardRef | str):
                text = annotation.__forward_arg__ if isinstance(annotation, ForwardRef) else annotation
                if text in state.followed:
                    return False
                # A `ForwardRef` may name the module it was written in, which is then where
                # it is resolved — `typing.get_type_hints` honours that, and so does this.
                declared_in = getattr(annotation, '__forward_module__', None) if annotation is not text else None
                state = state.following(text)
                annotation = _resolve_string_annotation(text, _module_source(declared_in) + state.sources)
                if annotation is _UNRESOLVED:
                    return False
            elif (alias := _type_alias(annotation)) is not None:
                if id(alias) in state.followed:
                    return False
                state = state.following(id(alias), zip(alias.__type_params__, get_args(annotation), strict=False))
                try:
                    annotation = alias.__value__
                except Exception:
                    return False
            elif isinstance(annotation, TypeVar) and annotation in state.bound:
                if id(annotation) in state.followed:
                    return False
                substituted = state.bound[annotation]
                state = state.following(id(annotation))
                annotation = substituted
            else:
                break

        # An annotation can be any object, so ask typing what this one is rather than
        # reading attributes off it: something carrying a `__metadata__` is not `Annotated`.
        origin = get_origin(annotation)

        if origin is Annotated:  # Annotated[Config, ...]
            return state.wants_marker(annotation.__origin__)

        if annotation is state.marker:
            return True

        if origin is Union or origin is UnionType:
            return any(state.wants_marker(arg) for arg in get_args(annotation))

        return False


class _Declaration:
    """Which of a target's parameters ask for the marker itself, answered on demand.

    A parameter's annotation is only resolved when a config actually supplies that
    parameter. Resolving one means evaluating whatever expression was written there, which
    can import a module or run code of its own, and a config has no business causing that
    for parameters it never sets. Answers are remembered, so each parameter costs that at
    most once per target.

    Reading a signature must never be what breaks `instantiate()`: a target free to define
    `__signature__`, `__getattr__` or `__class__` however it likes can make introspection
    raise anything at all, and a parameter that cannot be classified simply does not ask
    for the marker.
    """

    __slots__ = (
        '_answered',
        '_keywords',
        '_marker',
        '_positional',
        '_sources',
        '_target',
        '_var_keyword',
        '_var_positional',
    )

    def __init__(self, target: Any, marker: type):
        self._target = target
        self._marker = marker
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
            # exotic one can raise anything. Then nothing is classified, so nothing asks.
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
        """Does the parameter filled by positional argument `index` ask for the marker?"""
        if index < len(self._positional):
            return self._asks(self._positional[index])
        return self._var_positional is not None and self._asks(self._var_positional)

    def keyword(self, name: str) -> bool:
        """Does the parameter named `name` — or the `**kwargs` collecting it — ask for it?"""
        param = self._keywords.get(name, self._var_keyword)
        return param is not None and self._asks(param)

    def _asks(self, param: inspect.Parameter) -> bool:
        answer = self._answered.get(param.name)
        if answer is None:
            try:
                if self._sources is None:
                    self._sources = _annotation_sources(self._target)
                sources = _sources_for(self._sources, param)
                answer = _Resolution(self._marker, sources).wants_marker(param.annotation)
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


def declarations_for(marker: type) -> Callable[[Any], _Declaration]:
    """A lookup of which of a target's parameters ask for `marker` itself.

    The marker is a parameter rather than an import so that this module stays a reader of
    signatures, with nothing to say about what the class it looks for means.
    """

    # Reading the declaration means inspecting a signature and resolving annotations, which
    # is an order of magnitude more expensive than instantiating a small config. It depends
    # on the target alone, so cache it rather than paying it on every instantiate(). A
    # target's signature is read once and taken as settled: rewriting a live function's
    # __annotations__ after a config has instantiated it is not observed, and checking for
    # that would mean re-reading the signature every time, which is the cost the cache
    # exists to avoid.
    @functools.lru_cache(maxsize=1024)
    def cached(key: _TargetKey) -> _Declaration:
        return _Declaration(key.target, marker)

    def declaration_for(target: Any) -> _Declaration:
        return cached(_TargetKey(target))

    return declaration_for
