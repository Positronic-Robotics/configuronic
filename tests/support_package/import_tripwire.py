"""Tripwire module: nothing imports it, so its presence in ``sys.modules`` proves an import happened.

Used by the ``override_data`` tests to show that a rejected import string is refused
*before* anything is imported, rather than imported and then discarded.
"""

value = 'tripwire'
