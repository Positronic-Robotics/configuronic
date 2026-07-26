"""Targets whose annotations reach configuronic as source text.

``from __future__ import annotations`` turns every annotation in this module into a
string, which is the shape configuronic must still recognise when deciding that a
parameter wants the ``Config`` itself (issue #38).
"""

from __future__ import annotations

import functools

import configuronic as cfn
from configuronic import Config
from configuronic import Config as C
from tests.support_package import lazy_broken_metaclass, lazy_sibling_namespace, lazy_wrappers


class Pipeline:
    def __init__(self, fps: int = 30):
        self.fps = fps


def aliased_spelling(pipeline: cfn.Config, host: str = 'localhost'):
    return pipeline, host


def bare_spelling(pipeline: Config, host: str = 'localhost'):
    return pipeline, host


def quoted_spelling(pipeline: 'cfn.Config', host: str = 'localhost'):  # noqa: UP037 - the redundant quotes are the point
    """Quoted *and* postponed: the annotation is stored as the text ``"'cfn.Config'"``."""
    return pipeline, host


def alias_spelling(pipeline: C, host: str = 'localhost'):
    """The class under a local alias: nothing about the annotation says "Config"."""
    return pipeline, host


def optional_spelling(pipeline: Config | None = None):
    return pipeline


def with_unresolvable_neighbour(pipeline: cfn.Config, other: NeverDefined = None):  # noqa: F821
    """A parameter whose annotation cannot be resolved must not hide this one's."""
    return pipeline, other


def resolving_target(pipeline: Pipeline):
    return pipeline


# Module-level names defined in terms of each other: resolving one leads back to it.
CYCLIC_ALIAS = 'OTHER_CYCLIC_ALIAS'
OTHER_CYCLIC_ALIAS = 'CYCLIC_ALIAS'


def cyclic_alias_spelling(pipeline: CYCLIC_ALIAS):
    return pipeline


class Server:
    """A class target whose `__init__` annotations are postponed too."""

    def __init__(self, pipeline: cfn.Config, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host


class ClassBodyAlias:
    """The alias is bound in the class body, which is where the annotation was written."""

    Alias = cfn.Config

    def __init__(self, pipeline: Alias, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host

    def build(self, pipeline: Alias):
        """A bound method target — the alias is in this class body too."""
        return pipeline

    @staticmethod
    def make(pipeline: Alias):
        """A static method target: a plain function, reached through the class."""
        return pipeline


class PrivateClassBodyAlias:
    """The alias is private, so the class body holds it under a name nothing else uses."""

    __Alias = cfn.Config

    def __init__(self, pipeline: __Alias, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host


class InheritsClassBodyAlias(ClassBodyAlias):
    """Inherits the annotated `__init__`; the alias is in the base's body, not this one."""


def make_local_alias_holder():
    """An instance of a class defined inside a function, whose body binds the alias.

    Once this call has returned there is no way to reach the class from a qualified name,
    so a target has to carry the binding to it — which a decorator must not lose.
    """

    class LocalAlias:
        Alias = cfn.Config

        @lazy_wrappers.passthrough
        def build(self, pipeline: Alias):
            return pipeline

    return LocalAlias()


class PartialFactory:
    """Reached through the class, `configured` is a function generated inside functools."""

    def build(self, extra: str, pipeline: C):
        return pipeline, extra

    configured = functools.partialmethod(build, 'bound-extra')


class CallableBase:
    """A callable base class, subclassed in modules that never heard of the name `C`."""

    def __call__(self, pipeline: C, host: str = 'localhost'):
        return pipeline, host


class DecoratedInit:
    """A class whose `__init__` is decorated from a module that knows nothing about `cfn`."""

    @lazy_wrappers.passthrough
    def __init__(self, pipeline: cfn.Config, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host


class Factory:
    """A class whose signature comes from `__new__`; its `__init__` is `object.__init__`."""

    def __new__(cls, pipeline: cfn.Config, host: str = 'localhost'):
        instance = super().__new__(cls)
        instance.pipeline = pipeline
        instance.host = host
        return instance


class Building(type):
    def __call__(cls, pipeline: cfn.Config, host: str = 'localhost'):
        return pipeline, host


class Built(metaclass=Building):
    """A class whose signature comes from its metaclass' `__call__`."""


class BuiltByBrokenMeta(metaclass=lazy_broken_metaclass.BrokenAnnotationMeta):
    """`C` means `Config` here, but `pipeline` was written in the metaclass' module."""

    def __init__(self, other: C):
        self.other = other


class BuiltByMetaDeclaringTheSameParameter(metaclass=lazy_sibling_namespace.SameParameterMeta):
    """Declares `pipeline: C` too — identically to the metaclass that wrote the signature."""

    def __init__(self, pipeline: C, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host
