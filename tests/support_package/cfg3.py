import configuronic as cfn
from tests.support_package.cfg2 import return1 as cfg2_return1


@cfn.config()
def func_a():
    return 'a'


@cfn.config()
def func_b():
    return 'b'


@cfn.config()
def func_c():
    return 'c'


# Config that has a list with one default from a DIFFERENT module (cfg2)
# This proves that fallback doesn't use the default's module
@cfn.config(items=[cfg2_return1])
def process_items(items):
    return items


# Config that has a dict with one default from a DIFFERENT module (cfg2)
@cfn.config(config={'key1': cfg2_return1})
def process_config(config):
    return config


# Simple config for testing
@cfn.config()
def return_items(items):
    return items
