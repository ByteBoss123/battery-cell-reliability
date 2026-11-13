import os

import pytest

# In CI the services are required: a missing one must fail the build, not silently skip.
REQUIRED = os.environ.get("CI_REQUIRE_SERVICES") == "1"


def needs(var):
    if REQUIRED and not os.environ.get(var):
        raise RuntimeError(f"{var} is required in CI but not set")
    return pytest.mark.skipif(not os.environ.get(var), reason=f"{var} not set (integration service unavailable)")
