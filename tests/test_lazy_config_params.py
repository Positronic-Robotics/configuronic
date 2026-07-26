"""Tests for parameters that receive a `Config` instead of its instantiation.

See issue #38: a target that has to build a config later — more than once, or with
overrides it only learns at runtime — says so by annotating that parameter `cfn.Config`.
Everything else stays as it was: the stored value is an ordinary `Config`, so overrides
and traversal keep working.
"""

import functools
import inspect
import typing
from typing import Annotated, Optional

import pytest

import configuronic as cfn
from tests.support_package import lazy_annotations, lazy_declared_signature, lazy_wrappers


class Codec:
    def __init__(self, fps: int = 30):
        self.fps = fps


class Pipeline:
    def __init__(self, codec: Codec, model_path: str = 'base'):
        self.codec = codec
        self.model_path = model_path


class Config:
    """A class that happens to be named `Config` but is not configuronic's."""

    def __init__(self, value: int = 0):
        self.value = value


pipeline_cfg = cfn.Config(Pipeline, codec=cfn.Config(Codec))


@cfn.config(pipeline=pipeline_cfg, host='localhost')
def serve(pipeline: cfn.Config, host: str):
    return pipeline, host


# --- the annotation decides -----------------------------------------------------------


def test_annotated_parameter_receives_the_config():
    received, host = serve.instantiate()

    assert isinstance(received, cfn.Config)
    assert received.target is Pipeline
    assert host == 'localhost'


def test_unannotated_parameter_still_resolves():
    @cfn.config(pipeline=pipeline_cfg)
    def unannotated(pipeline):
        return pipeline

    assert isinstance(unannotated.instantiate(), Pipeline)


def test_differently_annotated_parameter_still_resolves():
    @cfn.config(pipeline=pipeline_cfg)
    def annotated_with_target(pipeline: Pipeline):
        return pipeline

    assert isinstance(annotated_with_target.instantiate(), Pipeline)


def test_other_parameters_of_the_same_target_still_resolve():
    @cfn.config(lazy=pipeline_cfg, eager=pipeline_cfg)
    def both(lazy: cfn.Config, eager):
        return lazy, eager

    lazy, eager = both.instantiate()

    assert isinstance(lazy, cfn.Config)
    assert isinstance(eager, Pipeline)


def test_unrelated_class_named_config_is_not_lazy():
    # The dispatch is on configuronic's Config, not on the name.
    @cfn.config(thing=cfn.Config(Config, value=7))
    def unrelated(thing: Config):
        return thing

    instance = unrelated.instantiate()

    assert isinstance(instance, Config)
    assert instance.value == 7


def test_unrelated_class_named_config_is_not_lazy_when_quoted():
    @cfn.config(thing=cfn.Config(Config, value=7))
    def unrelated(thing: 'Config'):
        return thing

    assert isinstance(unrelated.instantiate(), Config)


def test_quoted_annotation_is_recognised():
    @cfn.config(pipeline=pipeline_cfg)
    def quoted(pipeline: 'cfn.Config'):
        return pipeline

    assert isinstance(quoted.instantiate(), cfn.Config)


def test_optional_annotation_is_recognised():
    @cfn.config(pipeline=pipeline_cfg)
    def optional(pipeline: cfn.Config | None = None):
        return pipeline

    @cfn.config(pipeline=pipeline_cfg)
    def typing_optional(pipeline: Optional[cfn.Config] = None):  # noqa: UP045 - the typing spelling is the point
        return pipeline

    assert isinstance(optional.instantiate(), cfn.Config)
    assert isinstance(typing_optional.instantiate(), cfn.Config)


def test_annotated_wrapper_is_recognised():
    @cfn.config(pipeline=pipeline_cfg)
    def documented(pipeline: Annotated[cfn.Config, 'built per request']):
        return pipeline

    assert isinstance(documented.instantiate(), cfn.Config)


def test_container_annotation_keeps_resolving():
    # v1 hands over whole arguments only; a list of configs is still built, as before.
    @cfn.config(pipelines=[pipeline_cfg, pipeline_cfg])
    def many(pipelines: list[cfn.Config]):
        return pipelines

    assert [type(item) for item in many.instantiate()] == [Pipeline, Pipeline]


def test_non_config_value_on_a_lazy_parameter_passes_through():
    @cfn.config(pipeline=None)
    def nothing_stored(pipeline: cfn.Config | None):
        return pipeline

    @cfn.config(pipeline='not-a-config')
    def plain_value(pipeline: cfn.Config):
        return pipeline

    assert nothing_stored.instantiate() is None
    assert plain_value.instantiate() == 'not-a-config'


# --- string annotations (PEP 563) -----------------------------------------------------


def test_postponed_annotation_with_alias_spelling():
    cfg = cfn.Config(lazy_annotations.aliased_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    received, _ = cfg.instantiate()

    assert isinstance(received, cfn.Config)


def test_postponed_annotation_with_bare_spelling():
    cfg = cfn.Config(lazy_annotations.bare_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    received, _ = cfg.instantiate()

    assert isinstance(received, cfn.Config)


def test_postponed_quoted_annotation():
    # Quoting an annotation in a module that also postpones evaluation stores the *source
    # text* of the quoted expression, so it takes one more round to resolve.
    cfg = cfn.Config(lazy_annotations.quoted_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    received, _ = cfg.instantiate()

    assert isinstance(received, cfn.Config)


def test_postponed_annotation_on_a_class_target():
    server = cfn.Config(lazy_annotations.Server, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(server.pipeline, cfn.Config)
    assert isinstance(server.pipeline.instantiate(), lazy_annotations.Pipeline)


def test_postponed_alias_spelling():
    # `from configuronic import Config as C`: the annotation reads 'C', so only evaluating
    # it — rather than pattern-matching the source text — can tell what it means.
    cfg = cfn.Config(lazy_annotations.alias_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    received, _ = cfg.instantiate()

    assert isinstance(received, cfn.Config)


def test_postponed_annotation_on_a_class_with_a_decorated_init():
    # `inspect.signature` reports the wrapped `__init__`'s parameters, so the annotation
    # belongs to the module that wrote it, not to the decorator's.
    server = cfn.Config(lazy_annotations.DecoratedInit, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(server.pipeline, cfn.Config)


def test_postponed_annotation_on_a_class_built_by_new():
    factory = cfn.Config(lazy_annotations.Factory, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(factory.pipeline, cfn.Config)
    assert isinstance(factory.pipeline.instantiate(), lazy_annotations.Pipeline)


def test_postponed_annotation_on_a_class_built_by_a_metaclass():
    received, host = cfn.Config(lazy_annotations.Built, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(received, cfn.Config)
    assert host == 'localhost'


def test_cyclic_alias_spelling_is_not_lazy():
    # Module-level names defined in terms of each other resolve to each other forever.
    # No such cycle is a Config, and finding that out must not blow the stack.
    cfg = cfn.Config(lazy_annotations.cyclic_alias_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), lazy_annotations.Pipeline)


def test_postponed_annotation_using_a_class_body_alias():
    # The name is bound in the class body, so it is in scope where the annotation was
    # written — as it plainly is when the module does not postpone evaluation.
    server = cfn.Config(lazy_annotations.ClassBodyAlias, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(server.pipeline, cfn.Config)


def test_postponed_annotation_using_an_inherited_class_body_alias():
    # The `__init__` is inherited, so the body that binds the alias is the base's.
    cfg = cfn.Config(lazy_annotations.InheritsClassBodyAlias, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate().pipeline, cfn.Config)


def test_partialmethod_target_resolves_the_methods_annotations():
    # Through the class it is a function generated inside functools, which knows nothing
    # about the names the real method's annotations use; bound, it is a plain partial.
    factory = lazy_annotations.PartialFactory()

    unbound, extra = cfn.Config(lazy_annotations.PartialFactory.configured, factory, pipeline_cfg).instantiate()
    bound, _ = cfn.Config(factory.configured, pipeline_cfg).instantiate()

    assert isinstance(unbound, cfn.Config)
    assert isinstance(bound, cfn.Config)
    assert extra == 'bound-extra'


def test_static_method_target_resolves_a_class_body_alias():
    # A static method is a plain function with no binding, so only its qualified name says
    # which class body it was written in.
    cfg = cfn.Config(lazy_annotations.ClassBodyAlias.make, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), cfn.Config)


def test_bound_method_target_resolves_a_class_body_alias():
    holder = lazy_annotations.ClassBodyAlias(pipeline=None)

    cfg = cfn.Config(holder.build, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), cfn.Config)


def test_decorated_bound_method_keeps_what_it_is_bound_to():
    # The class is defined inside a function, so its body is reachable only through the
    # binding the target carries — and a decorator leads through `__wrapped__` to a
    # function that knows nothing about the instance.
    holder = lazy_annotations.make_local_alias_holder()

    cfg = cfn.Config(holder.build, pipeline=cfn.Config(lazy_annotations.Pipeline))
    # Wrapped again, so the binding sits in the middle of the chain rather than at its head.
    partially_applied = cfn.Config(functools.partial(holder.build), pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), cfn.Config)
    assert isinstance(partially_applied.instantiate(), cfn.Config)


@pytest.mark.skipif(not hasattr(typing, 'TypeAliasType'), reason='`type X = ...` aliases are 3.12+')
def test_type_alias_is_followed():
    deferred = typing.TypeAliasType('Deferred', cfn.Config)
    maybe_deferred = typing.TypeAliasType('MaybeDeferred', cfn.Config | None)

    @cfn.config(pipeline=pipeline_cfg)
    def via_alias(pipeline: deferred):
        return pipeline

    @cfn.config(pipeline=pipeline_cfg)
    def via_optional_alias(pipeline: maybe_deferred):
        return pipeline

    assert isinstance(via_alias.instantiate(), cfn.Config)
    assert isinstance(via_optional_alias.instantiate(), cfn.Config)


@pytest.mark.skipif(not hasattr(typing, 'TypeAliasType'), reason='`type X = ...` aliases are 3.12+')
def test_specialized_type_alias_is_followed():
    # `type Deferred[T] = T | None` used as `Deferred[Config]` is a generic alias over the
    # alias, not the alias itself, and what it stands for is written in terms of `T`.
    parameter = typing.TypeVar('T')
    identity = typing.TypeAliasType('Identity', parameter, type_params=(parameter,))
    deferred = typing.TypeAliasType('Deferred', parameter | None, type_params=(parameter,))
    marked = typing.TypeAliasType('Marked', typing.Annotated[parameter, 'note'], type_params=(parameter,))

    @cfn.config(pipeline=pipeline_cfg)
    def via_identity(pipeline: identity[cfn.Config]):
        return pipeline

    @cfn.config(pipeline=pipeline_cfg)
    def via_optional(pipeline: deferred[cfn.Config]):
        return pipeline

    @cfn.config(pipeline=pipeline_cfg)
    def via_annotated(pipeline: marked[cfn.Config]):
        return pipeline

    @cfn.config(pipeline=pipeline_cfg)
    def specialized_with_something_else(pipeline: identity[int]):
        return pipeline

    assert isinstance(via_identity.instantiate(), cfn.Config)
    assert isinstance(via_optional.instantiate(), cfn.Config)
    assert isinstance(via_annotated.instantiate(), cfn.Config)
    assert isinstance(specialized_with_something_else.instantiate(), Pipeline)


@pytest.mark.skipif(not hasattr(typing, 'TypeAliasType'), reason='`type X = ...` aliases are 3.12+')
def test_specialized_type_alias_of_a_container_is_not_lazy():
    # `Boxed[Config]` stands for `list[Config]`: a container of configs resolves as before,
    # since only a whole argument can be handed over unresolved.
    parameter = typing.TypeVar('T')
    boxed = typing.TypeAliasType('Boxed', list[parameter], type_params=(parameter,))

    @cfn.config(pipeline=[pipeline_cfg])
    def via_container_alias(pipeline: boxed[cfn.Config]):
        return pipeline

    assert [type(item) for item in via_container_alias.instantiate()] == [Pipeline]


@pytest.mark.skipif(not hasattr(typing, 'TypeAliasType'), reason='`type X = ...` aliases are 3.12+')
def test_type_parameter_bound_to_itself_is_not_lazy():
    # Specializing an alias with its own type parameter binds `T` to `T`; substituting it
    # must stop rather than spin.
    parameter = typing.TypeVar('T')
    self_bound = typing.TypeAliasType('SelfBound', parameter, type_params=(parameter,))

    @cfn.config(pipeline=pipeline_cfg)
    def via_self_bound(pipeline: self_bound[parameter]):
        return pipeline

    assert isinstance(via_self_bound.instantiate(), Pipeline)


@pytest.mark.skipif(not hasattr(typing, 'TypeAliasType'), reason='`type X = ...` aliases are 3.12+')
def test_self_referential_type_alias_is_not_lazy():
    # `type SelfRef = SelfRef` evaluates to itself; following it must stop, not recurse.
    # Written through exec so the 3.12 syntax never reaches the parser on older versions.
    namespace: dict = {}
    exec('type SelfRef = SelfRef', namespace)  # noqa: S102 - the point is the 3.12-only syntax
    self_referential = namespace['SelfRef']

    @cfn.config(pipeline=pipeline_cfg)
    def via_self_reference(pipeline: self_referential):
        return pipeline

    assert isinstance(via_self_reference.instantiate(), Pipeline)


def test_annotation_is_not_resolved_in_a_sibling_namespace():
    # `pipeline` is written in the metaclass' module and cannot be resolved there. The
    # class' own module binds that name to `Config`, but it did not write the parameter,
    # so it does not get to answer for it: the annotation is simply unresolved.
    cfg = cfn.Config(lazy_annotations.BuiltByBrokenMeta, pipeline=pipeline_cfg)

    received, _ = cfg.instantiate()

    assert isinstance(received, Pipeline)


def test_identical_declaration_in_a_sibling_namespace_does_not_answer():
    # The metaclass wrote `pipeline: C` and cannot resolve `C`; the class' own `__init__`
    # declares an identical-looking parameter in a module where `C` *is* Config. Only the
    # first candidate can be the one the signature came from, so `C` stays unresolved.
    cfg = cfn.Config(lazy_annotations.BuiltByMetaDeclaringTheSameParameter, pipeline=pipeline_cfg)

    received, _ = cfg.instantiate()

    assert isinstance(received, Pipeline)


def test_forward_reference_resolves_in_the_module_it_names():
    forward = typing.ForwardRef('C', module=lazy_annotations.__name__)

    @cfn.config(pipeline=pipeline_cfg)
    def via_forward_ref(pipeline: forward):
        return pipeline

    assert isinstance(via_forward_ref.instantiate(), cfn.Config)


def test_postponed_optional_annotation():
    cfg = cfn.Config(lazy_annotations.optional_spelling, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), cfn.Config)


def test_unresolvable_annotation_on_another_parameter_is_ignored():
    # Resolution is per parameter, so a forward reference that cannot be resolved
    # elsewhere in the signature does not disable the feature for this one.
    cfg = cfn.Config(lazy_annotations.with_unresolvable_neighbour, pipeline=cfn.Config(lazy_annotations.Pipeline))

    received, other = cfg.instantiate()

    assert isinstance(received, cfn.Config)
    assert other is None


def test_postponed_non_config_annotation_still_resolves():
    cfg = cfn.Config(lazy_annotations.resolving_target, pipeline=cfn.Config(lazy_annotations.Pipeline))

    assert isinstance(cfg.instantiate(), lazy_annotations.Pipeline)


def test_forward_reference_inside_a_union_is_recognised():
    @cfn.config(pipeline=pipeline_cfg)
    def forward(pipeline: Optional['cfn.Config'] = None):  # noqa: UP045 - a bare `'cfn.Config' | None` is a TypeError
        return pipeline

    assert isinstance(forward.instantiate(), cfn.Config)


def test_annotation_that_cannot_be_resolved_is_not_lazy():
    # An annotation naming Config but unresolvable is treated as "not a Config annotation",
    # never as an error: instantiate() must not start failing over a bad forward reference.
    @cfn.config(pipeline=pipeline_cfg)
    def unresolvable(pipeline: 'NoSuchConfig'):  # noqa: F821 - deliberately undefined
        return pipeline

    assert isinstance(unresolvable.instantiate(), Pipeline)


def test_annotations_of_parameters_the_config_does_not_set_are_left_alone():
    # Resolving an annotation evaluates whatever expression was written there. A config
    # that never sets that parameter has no business causing that.
    evaluated = []

    class Watched:
        def __getattr__(self, name):
            evaluated.append(name)
            raise AttributeError(name)

    watched = Watched()
    namespace = {'watched': watched, 'cfn': cfn}
    exec(  # noqa: S102 - postponed annotations in a module we build here
        'from __future__ import annotations\n'
        'def target(untouched: watched.Thing = None, pipeline: cfn.Config = None):\n'
        '    return pipeline\n',
        namespace,
    )

    received = cfn.Config(namespace['target'], pipeline=pipeline_cfg).instantiate()

    assert isinstance(received, cfn.Config)
    assert evaluated == []


def test_introspection_that_raises_does_not_break_instantiate():
    # A target is free to define `__signature__` however it likes; reading it must not be
    # what breaks building a config.
    class Hostile:
        @property
        def __signature__(self):
            raise RuntimeError('signature is not available')

        def __call__(self, pipeline):
            return pipeline

    assert isinstance(cfn.Config(Hostile(), pipeline=pipeline_cfg).instantiate(), Pipeline)


def test_annotation_object_is_never_compared():
    # An annotation is any object, and reading a signature must not run its `__eq__`.
    class Hostile:
        def __eq__(self, other):
            raise AssertionError('annotations must not be compared')

    hostile = Hostile()

    @cfn.config(pipeline=pipeline_cfg)
    def annotated_with_an_object(pipeline: hostile):
        return pipeline

    assert isinstance(annotated_with_an_object.instantiate(), Pipeline)


def test_annotation_carrying_metadata_is_not_mistaken_for_annotated():
    # An annotation can be any object. One that happens to carry `__metadata__` is not
    # `Annotated`, and reading `__origin__` off it must not break instantiate().
    class Marked:
        __metadata__ = ('not really Annotated',)

    @cfn.config(pipeline=pipeline_cfg)
    def marked(pipeline: Marked):
        return pipeline

    assert isinstance(marked.instantiate(), Pipeline)


def test_inherited_call_resolves_in_its_defining_module():
    # `__call__` comes from a base class in another module, and its annotation uses a name
    # only that module has.
    class Server(lazy_annotations.CallableBase):
        pass

    received, _ = cfn.Config(Server(), pipeline=pipeline_cfg).instantiate()

    assert isinstance(received, cfn.Config)


def test_callable_object_target_resolves_its_annotations():
    # A target that is neither a function nor a class has no __globals__, so the
    # annotation is resolved in the module its class came from.
    class Server:
        def __call__(self, pipeline: 'cfn.Config'):
            return pipeline

    assert isinstance(cfn.Config(Server(), pipeline=pipeline_cfg).instantiate(), cfn.Config)


# --- overriding a lazy parameter ------------------------------------------------------


def test_override_swaps_the_config():
    other = cfn.Config(Pipeline, codec=cfn.Config(Codec, fps=60), model_path='other')

    received, _ = serve.override(pipeline=other).instantiate()

    assert received.instantiate().model_path == 'other'


def test_dotted_override_reaches_into_the_lazy_parameter():
    received, _ = serve.override(**{'pipeline.codec.fps': 10}).instantiate()

    assert received.instantiate().codec.fps == 10


def test_import_string_override_swaps_the_config():
    # `--pipeline=@module.other_pipeline` on the CLI: resolved at override time, handed
    # over unresolved at instantiate time.
    received, _ = serve.override(pipeline='@tests.test_lazy_config_params.pipeline_cfg').instantiate()

    assert received.target is Pipeline


def test_override_leaves_the_base_untouched():
    variant = serve.override(**{'pipeline.codec.fps': 10})

    assert variant.instantiate()[0].instantiate().codec.fps == 10
    assert serve.instantiate()[0].instantiate().codec.fps == 30


def test_variants_receive_independent_configs():
    fast = serve.override(**{'pipeline.codec.fps': 60})
    slow = serve.override(**{'pipeline.codec.fps': 5})

    fast_received, _ = fast.instantiate()
    slow_received, _ = slow.instantiate()

    assert fast_received is not slow_received
    assert fast_received.instantiate().codec.fps == 60
    assert slow_received.instantiate().codec.fps == 5


def test_received_config_is_the_stored_one():
    # Handed over as stored — not a copy — so the target sees exactly what `--help` shows.
    received, _ = serve.instantiate()

    assert received is serve.kwargs['pipeline']


# --- what the target does with it ------------------------------------------------------


def test_target_can_instantiate_the_received_config_more_than_once():
    received, _ = serve.instantiate()

    first = received.instantiate()
    second = received.instantiate()

    assert isinstance(first, Pipeline)
    assert first is not second


def test_target_can_apply_per_call_overrides():
    # The motivating case: a server applying per-connection overrides to one pipeline.
    received, _ = serve.instantiate()

    fast = received.override(**{'codec.fps': 120}).instantiate()
    slow = received.override(**{'codec.fps': 1}).instantiate()

    assert (fast.codec.fps, slow.codec.fps) == (120, 1)
    assert received.instantiate().codec.fps == 30


def test_override_data_on_the_received_config_still_refuses_imports():
    received, _ = serve.instantiate()

    assert received.override_data(**{'codec.fps': 10}).instantiate().codec.fps == 10

    try:
        received.override_data(codec='@os.system')
    except cfn.ImportNotAllowedError as e:
        assert e.key == 'codec'
    else:
        raise AssertionError('override_data accepted an import string')


def test_lazy_config_is_visible_in_the_string_form():
    # What `--help` prints: the contents of the pipeline, not an opaque object.
    printed = str(serve)

    assert 'codec' in printed
    assert 'fps' not in printed  # only set values are printed; fps keeps its default

    assert 'fps' in str(serve.override(**{'pipeline.codec.fps': 10}))


def test_get_required_args_reports_args_nested_in_a_lazy_parameter():
    cfg = cfn.Config(serve.target, pipeline=cfn.Config(Pipeline), host='localhost')

    assert cfn.get_required_args(cfg) == ['pipeline.codec']


# --- targets other than plain functions ------------------------------------------------


def test_class_target_receives_the_config():
    class Server:
        def __init__(self, pipeline: cfn.Config, host: str = 'localhost'):
            self.pipeline = pipeline
            self.host = host

    server = cfn.Config(Server, pipeline=pipeline_cfg).instantiate()

    assert isinstance(server.pipeline, cfn.Config)
    assert isinstance(server.pipeline.instantiate(), Pipeline)


def test_positional_argument_is_handed_over():
    def positional(pipeline: cfn.Config, eager: Pipeline):
        return pipeline, eager

    received, eager = cfn.Config(positional, pipeline_cfg, pipeline_cfg).instantiate()

    assert isinstance(received, cfn.Config)
    assert isinstance(eager, Pipeline)


def test_var_positional_is_handed_over():
    def collect(*pipelines: cfn.Config):
        return pipelines

    received = cfn.Config(collect, pipeline_cfg, pipeline_cfg).instantiate()

    assert [isinstance(item, cfn.Config) for item in received] == [True, True]


def test_var_keyword_is_handed_over():
    def collect(**pipelines: cfn.Config):
        return pipelines

    received = cfn.Config(collect, left=pipeline_cfg, right=pipeline_cfg).instantiate()

    assert sorted(received) == ['left', 'right']
    assert all(isinstance(item, cfn.Config) for item in received.values())


def test_keyword_only_parameter_is_handed_over():
    def keyword_only(*, pipeline: cfn.Config):
        return pipeline

    assert isinstance(cfn.Config(keyword_only, pipeline=pipeline_cfg).instantiate(), cfn.Config)


def test_target_without_an_introspectable_signature_still_instantiates():
    # C callables often refuse `inspect.signature`; nothing is annotated there anyway.
    assert cfn.Config(dict, a=1).instantiate() == {'a': 1}


def test_partial_target_resolves_the_wrapped_functions_annotations():
    # `inspect.signature` reports the wrapped function's parameters, so its annotations
    # must be resolved where they were written, not in functools.
    target = functools.partial(lazy_annotations.aliased_spelling, host='127.0.0.1')

    received, host = cfn.Config(target, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(received, cfn.Config)
    assert host == '127.0.0.1'


def test_partial_target_shifts_positional_slots():
    def prefixed(prefix: str, pipeline: cfn.Config):
        return prefix, pipeline

    prefix, received = cfn.Config(functools.partial(prefixed, 'p'), pipeline_cfg).instantiate()

    assert prefix == 'p'
    assert isinstance(received, cfn.Config)


def test_wraps_decorated_target_resolves_the_wrapped_functions_annotations():
    target = lazy_wrappers.passthrough(lazy_annotations.aliased_spelling)

    received, _ = cfn.Config(target, pipeline=cfn.Config(lazy_annotations.Pipeline)).instantiate()

    assert isinstance(received, cfn.Config)


def test_declared_signature_wins_over_the_wrapped_function():
    # `inspect.signature` stops at a `__signature__`, so the parameters — and the names
    # their annotations use — belong to the wrapper, not to what it wraps.
    target = lazy_declared_signature.with_declared_signature(lazy_wrappers.echo)

    assert isinstance(cfn.Config(target, pipeline=pipeline_cfg).instantiate(), cfn.Config)


def test_circular_wrapper_chain_does_not_spin():
    def target(pipeline: 'cfn.Config'):
        return pipeline

    # `inspect.signature` stops unwrapping at a `__signature__`, so it accepts this target
    # and hands us annotations to resolve — while the chain to the function that wrote them
    # is circular.
    target.__signature__ = inspect.signature(target)
    target.__wrapped__ = target

    assert isinstance(cfn.Config(target, pipeline=pipeline_cfg).instantiate(), cfn.Config)


def test_unhashable_target_is_handled():
    # The per-target declaration is cached, and an unhashable target cannot be a cache key.
    class Server:
        __hash__ = None

        def __call__(self, pipeline: cfn.Config, eager: Pipeline):
            return pipeline, eager

    received, eager = cfn.Config(Server(), pipeline=pipeline_cfg, eager=pipeline_cfg).instantiate()

    assert isinstance(received, cfn.Config)
    assert isinstance(eager, Pipeline)


def test_equal_targets_with_different_signatures_are_not_confused():
    # The cache is keyed by identity: targets that compare equal can still report
    # different signatures, and each must get its own declaration.
    class Server:
        def __init__(self, lazy: bool):
            annotation = cfn.Config if lazy else Pipeline
            self.__signature__ = inspect.Signature([
                inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation)
            ])

        def __call__(self, pipeline):
            return pipeline

        def __eq__(self, other):
            return isinstance(other, Server)

        def __hash__(self):
            return 0

    lazy_target = cfn.Config(Server(lazy=True), pipeline=pipeline_cfg)
    eager_target = cfn.Config(Server(lazy=False), pipeline=pipeline_cfg)

    assert isinstance(lazy_target.instantiate(), cfn.Config)
    assert isinstance(eager_target.instantiate(), Pipeline)


def test_lazy_parameter_inside_a_nested_config():
    @cfn.config(server=cfn.Config(serve.target, pipeline=pipeline_cfg, host='localhost'))
    def app(server):
        return server

    received, _ = app.instantiate()

    assert isinstance(received, cfn.Config)
    assert received.target is Pipeline
