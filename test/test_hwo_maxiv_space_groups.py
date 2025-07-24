import pytest

from mxcubecore.HardwareObjects.MAXIV.space_groups import (
    SPACE_GROUPS,
    SpaceGroup,
    _get_space_group,
    get_full_name,
    get_number,
)


@pytest.mark.parametrize("spg", ["P21", "H32", "p312"])
def test_get_existing_space_group(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    assert isinstance(_get_space_group(spg), SpaceGroup)


@pytest.mark.parametrize("spg", ["foo", "blah", ""])
def test_get_nonexisting_space_group(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    with pytest.raises(ValueError, match="Unknown space group short name: " + spg):
        _get_space_group(spg)


@pytest.mark.parametrize("spg", ["P21", "H32", "p312"])
def test_get_existing_space_group_full_name(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    assert get_full_name(spg) == SPACE_GROUPS[spg.upper()].full_name


@pytest.mark.parametrize("spg", ["foo", "blah", ""])
def test_get_nonexisting_space_group_full_name(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    with pytest.raises(ValueError, match="Unknown space group short name: " + spg):
        get_full_name(spg)


@pytest.mark.parametrize("spg", ["P21", "H32", "p312"])
def test_get_existing_space_group_number(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    assert get_number(spg) == SPACE_GROUPS[spg.upper()].number


@pytest.mark.parametrize("spg", ["foo", "blah", ""])
def test_get_nonexisting_space_group_number(spg):
    """
    Test that the full name of a space group can be retrieved correctly.
    """
    with pytest.raises(ValueError, match="Unknown space group short name: " + spg):
        get_number(spg)
