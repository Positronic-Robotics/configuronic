"""A decorator that lives away from the functions it wraps.

`functools.wraps` keeps the wrapper's own globals while `inspect.signature` reports the
wrapped function's parameters, so a wrapped target's string annotations have to be
resolved where they were written. This module deliberately never imports configuronic.
"""

import functools


def passthrough(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper
