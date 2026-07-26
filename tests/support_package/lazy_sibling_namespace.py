"""A metaclass whose `__call__` declares the same parameter as the class' `__init__`.

Both spell the annotation `C`, but only the class' module binds that name — so this is
where "the namespace that wrote the parameter answers for it" has to hold even when a
sibling candidate declares an identical-looking one.
"""

from __future__ import annotations


class SameParameterMeta(type):
    def __call__(cls, pipeline: C, host: str = 'localhost'):  # noqa: F821 - unresolvable here, deliberately
        return pipeline, host
