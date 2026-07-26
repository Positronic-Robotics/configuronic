"""Targets whose annotations reach configuronic as source text.

``from __future__ import annotations`` turns every annotation in this module into a
string, which is the shape configuronic must still recognise when deciding that a
parameter wants the ``Config`` itself (issue #38).
"""

from __future__ import annotations

import configuronic as cfn
from configuronic import Config


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


def optional_spelling(pipeline: Config | None = None):
    return pipeline


def with_unresolvable_neighbour(pipeline: cfn.Config, other: NeverDefined = None):  # noqa: F821
    """A parameter whose annotation cannot be resolved must not hide this one's."""
    return pipeline, other


def resolving_target(pipeline: Pipeline):
    return pipeline


class Server:
    """A class target whose `__init__` annotations are postponed too."""

    def __init__(self, pipeline: cfn.Config, host: str = 'localhost'):
        self.pipeline = pipeline
        self.host = host
