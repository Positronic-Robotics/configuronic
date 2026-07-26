"""Targets that declare their own `__signature__`.

`inspect.signature` stops unwrapping at a `__signature__` and reports the parameters
declared there, so their annotations belong where the declaration was written — this
module for the wrapper below, and the class body for the class further down.
"""

import functools
import inspect

from configuronic import Config as C
from tests.support_package import lazy_annotations, lazy_signature_metaclass


def with_declared_signature(func):
    """The wrapped function's module knows nothing about the name `C`."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper.__signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='C')
    ])
    return wrapper


class TakesAPipeline:
    """Provides the constructor, and annotates nothing."""

    def __init__(self, pipeline):
        self.pipeline = pipeline


class DeclaresItsOwnSignature(TakesAPipeline):
    """Inherits that constructor, so only the signature declared here has the parameters.

    `Alias` is bound in this class body — the same body the declaration is written in, and
    the only scope in which its annotation means anything.
    """

    Alias = C

    __signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Alias')
    ])


class BuiltByMetaclassDeclaringInItsBody(TakesAPipeline, metaclass=lazy_signature_metaclass.DeclaresInItsBody):
    """Declares no signature of its own, so the one found through the metaclass is used.

    The name that signature annotates with is bound in the metaclass body, and nothing in
    *this* module binds it.
    """


class BuiltByMetaclassDeclaringFromItsModule(TakesAPipeline, metaclass=lazy_signature_metaclass.DeclaresFromItsModule):
    """The same, with the name bound at module level beside the metaclass."""


class DeclaresOverUnresolvableInit(lazy_annotations.UnresolvableInit):
    """Declares its own signature, and inherits an `__init__` declaring the same thing.

    The inherited constructor spells `pipeline: Alias` where nothing binds `Alias`; this
    body does bind it. Only one of the two is what `inspect.signature` reports, and it is
    not the constructor.
    """

    Alias = C

    __signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Alias')
    ])
