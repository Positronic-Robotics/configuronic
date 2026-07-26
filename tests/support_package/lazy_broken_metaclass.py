"""A metaclass whose `__call__` annotation cannot be resolved in its own module.

The class built with it lives in a module where that same name *does* mean `Config`, which
is where "resolve an annotation only where it was written" becomes visible: the annotation
is broken, and a sibling namespace must not answer for it.
"""

from __future__ import annotations


class BrokenAnnotationMeta(type):
    def __call__(cls, pipeline: C, host: str = 'localhost'):  # noqa: F821 - unresolvable here, deliberately
        return pipeline, host
