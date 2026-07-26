"""A module naming an imported alias `C` — the very spelling that alias' value quotes.

`C` is the alias here and `Config` in the module the alias came from, so the same text
appears twice on the way to the answer while meaning something different each time.
"""

from __future__ import annotations

from tests.support_package.lazy_annotations import QUOTED_VALUE_ALIAS as C


def shadowed_spelling(pipeline: C):
    return pipeline
