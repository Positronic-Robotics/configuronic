import sys

import configuronic as cfn
from tests.support_package.subpkg.a import A


def wrapper(inner):
    return inner


inner_cfg = cfn.Config(A, value=1)
outer_cfg = cfn.Config(wrapper, inner=inner_cfg)

if __name__ == '__main__':
    from tests.support_package.b import B

    result = outer_cfg.override(inner='..b.B').instantiate()
    assert result is B, f'Expected class B, got {result}'
    print('OK')
    sys.exit(0)
