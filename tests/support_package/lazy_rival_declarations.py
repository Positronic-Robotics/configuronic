"""A class whose constructor cannot resolve what the metaclass building it can.

The mirror of `lazy_sibling_namespace`: there the metaclass' annotation is the broken one,
here it is the class'. Which of the two supplied the signature is CPython's business, so
neither ordering may be what decides the answer.
"""

from __future__ import annotations

from tests.support_package import lazy_annotations


class BuiltByResolvableMeta(metaclass=lazy_annotations.ForwardingMeta):
    """`C` is `Config` where the metaclass wrote `pipeline: C`, and nothing here."""

    def __init__(self, pipeline: C, host: str = 'localhost'):  # noqa: F821 - unresolvable here, deliberately
        self.pipeline = pipeline
        self.host = host
