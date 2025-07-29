import configuronic as cfn
from tests.support_package.b import B
from tests.support_package.subpkg.a import A

a_cfg_value1 = cfn.Config(A, value=1)
a_cfg_value2 = cfn.Config(A, value=2)
b_cfg_value1 = cfn.Config(B, value=1)
b_cfg_value2 = cfn.Config(B, value=2)
