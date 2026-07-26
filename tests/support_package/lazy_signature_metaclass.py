"""Metaclasses that declare the signature of the classes they build.

`inspect.signature` finds `__signature__` through the metaclass when the class itself does
not define one, so the annotations in it were written *here* — in a metaclass body, or at
module level beside it. The classes built by these live in another module, which binds
neither name.
"""

import inspect

import configuronic as cfn

ModuleAlias = cfn.Config


class DeclaresInItsBody(type):
    Alias = cfn.Config

    __signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='Alias')
    ])


class DeclaresFromItsModule(type):
    __signature__ = inspect.Signature([
        inspect.Parameter('pipeline', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation='ModuleAlias')
    ])
