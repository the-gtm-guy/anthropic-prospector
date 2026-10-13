"""The pytest warning policy must turn Pydantic V1-style API use into a test failure."""

import pytest
from pydantic import BaseModel
from pydantic.warnings import PydanticDeprecationWarning


class _Model(BaseModel):
    x: int = 1


def test_pydantic_v1_api_use_fails_the_suite() -> None:
    with pytest.raises(PydanticDeprecationWarning):
        _Model().dict()  # type: ignore[deprecated]
