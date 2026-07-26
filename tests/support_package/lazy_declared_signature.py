"""A wrapper that declares its own `__signature__`.

`inspect.signature` stops unwrapping at a `__signature__` and reports the parameters
declared here, so their annotations belong to *this* module — the wrapped function's
module knows nothing about the name `C`.
"""

import functools
import inspect

from configuronic import Config as C  # noqa: F401 - named by the annotation string below


def with_declared_signature(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper.__signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='C')
    ])
    return wrapper
