import pytest
from unpy._version_iv import VERSION_MAX, VERSION_MIN, VersionIV


def test_setops_unary_unbounded():
    iv = VersionIV(..., ...)

    assert iv
    assert repr(iv) == "VersionIV((0,), ...)"
    assert str(iv) == "[0; ...)"

    assert VERSION_MIN in iv
    assert VERSION_MAX not in iv
    assert (0, 0) in iv
    assert (1_3_3_7, 0xDEADBEEF) in iv

    assert iv.start == VERSION_MIN
    assert iv.stop is None
    assert iv.step == (0, 1)

    assert not iv.bounded
    assert not iv.bounded_below
    assert not iv.bounded_above


def test_setops_unary_empty():
    iv = VersionIV((3, 14), (3, 14))

    assert not iv
    assert repr(iv) == "VersionIV((0,), (0,))"
    assert str(iv) == "∅"

    assert VERSION_MIN not in iv
    assert VERSION_MAX not in iv
    assert (3, 14) not in iv

    assert iv.start == (0,)
    assert iv.stop == (0,)
    assert iv.step == (0, 0)

    assert iv.bounded
    assert iv.bounded_below
    assert iv.bounded_above


def test_setops_unary_bounded_above():
    iv = VersionIV(..., (3, 14))

    assert iv
    assert repr(iv) == "VersionIV((0,), (3, 14))"
    assert str(iv) == "[0; 3.14)"

    assert VERSION_MIN in iv
    assert VERSION_MAX not in iv
    assert (0, 0) in iv
    assert (3, 13, 0, "candidate", 3) in iv
    assert (3, 14) not in iv

    assert iv.start == VERSION_MIN
    assert iv.stop == (3, 14)
    assert iv.step == (0, 1)

    assert not iv.bounded
    assert not iv.bounded_below
    assert iv.bounded_above


def test_setops_unary_bounded_below():
    iv = VersionIV((3, 12), ...)

    assert iv
    assert repr(iv) == "VersionIV((3, 12), ...)"
    assert str(iv) == "[3.12; ...)"

    assert VERSION_MIN not in iv
    assert VERSION_MAX not in iv
    assert (3, 11) not in iv
    assert (3, 12) in iv
    assert (3, 13) in iv
    assert (99, 99) in iv

    assert iv.start == (3, 12)
    assert iv.stop is None
    assert iv.step == (0, 1)

    assert not iv.bounded
    assert iv.bounded_below
    assert not iv.bounded_above


def test_setops_unary_bounded():
    iv = VersionIV((3, 13), (3, 14))

    assert iv
    assert repr(iv) == "VersionIV((3, 13), (3, 14))"
    assert str(iv) == "[3.13; 3.14)"

    assert VERSION_MIN not in iv
    assert VERSION_MAX not in iv
    assert (3, 12) not in iv
    assert (3, 12, 7, "final", 0) not in iv
    assert (3, 13) in iv
    assert (3, 13, 0, "candidate", 3) in iv
    assert (3, 14) not in iv

    assert iv.start == (3, 13)
    assert iv.stop == (3, 14)
    assert iv.step == (0, 1)

    assert iv.bounded
    assert iv.bounded_below
    assert iv.bounded_above


@pytest.mark.parametrize(
    ("iv1", "iv2"),
    [
        (VersionIV(..., ...), VersionIV(..., ...)),
        (VersionIV((1, 0), (0, 1)), VersionIV((3, 14), (3, 14))),
        (VersionIV(..., (3, 14)), VersionIV(..., (3, 14))),
        (VersionIV((3, 12), ...), VersionIV((3, 12), ...)),
        (VersionIV((3, 13), (3, 14)), VersionIV((3, 13), (3, 14))),
    ],
)
def test_setops_same(iv1: VersionIV, iv2: VersionIV):
    assert hash(iv1) == hash(iv2)
    assert iv1 == iv2
    assert not iv1 != iv2  # noqa: SIM202
    assert not iv1 < iv2
    assert iv1 <= iv2
    assert iv1 >= iv2
    assert not iv1 > iv2

    assert iv1 & iv2 == iv1 == iv2
    assert iv1 & iv1 == iv2 & iv2

    assert iv1 | iv2 == iv1 == iv2
    assert iv1 | iv2 == iv2 | iv1
    assert iv1 | iv1 == iv2 | iv2

    assert not iv1 - iv2
    assert not iv2 - iv1


@pytest.mark.parametrize(
    "iv1",
    [
        VersionIV(..., ...),
        VersionIV(..., (3, 14)),
        VersionIV((3, 11), ...),
        VersionIV((3, 11), (3, 14)),
    ],
)
@pytest.mark.parametrize(
    "iv2",
    [
        VersionIV(VERSION_MAX, VERSION_MIN),
        VersionIV((3, 12), (3, 13)),
        VersionIV((3, 12), (3, 14)),
        VersionIV((3, 11), (3, 13)),
    ],
)
def test_binops_subset(iv1: VersionIV, iv2: VersionIV):
    assert iv1 != iv2
    assert iv2 != iv1
    assert not iv1 == iv2  # noqa: SIM201
    assert not iv2 == iv1  # noqa: SIM201
    assert hash(iv1) != hash(iv2)

    assert iv1 > iv2
    assert iv2 < iv1
    assert not iv1 < iv2
    assert not iv2 > iv1

    assert iv1 >= iv2
    assert iv2 <= iv1
    assert not iv1 <= iv2
    assert not iv2 >= iv1

    assert iv1 & iv2 == iv2
    assert iv2 & iv1 == iv2

    assert iv1 | iv2 == iv1
    assert iv2 | iv1 == iv1

    assert (iv1 & iv2) | iv1 == iv1
    assert iv1 & (iv2 | iv1) == iv1

    assert not iv2 - iv1
    assert iv2 - iv1 == iv1 - iv1 == iv2 - iv2


@pytest.mark.parametrize(
    ("iv1", "iv2"),
    [
        (VersionIV(..., ...), VersionIV(..., VERSION_MIN)),
        (VersionIV(..., ...), VersionIV(..., (3, 10))),
        (VersionIV(..., ...), VersionIV((3, 11), ...)),
        (VersionIV(..., (3, 14)), VersionIV(..., VERSION_MIN)),
        (VersionIV(..., (3, 14)), VersionIV(..., (3, 10))),
        (VersionIV(..., (3, 14)), VersionIV((3, 11), ...)),
        (VersionIV(..., (3, 14)), VersionIV((3, 11), (3, 14))),
        (VersionIV((3, 10), ...), VersionIV(..., VERSION_MIN)),
        (VersionIV((3, 10), ...), VersionIV(..., (3, 13))),
        (VersionIV((3, 10), ...), VersionIV((3, 11), ...)),
        (VersionIV((3, 10), ...), VersionIV((3, 10), (3, 13))),
        (VersionIV((3, 10), (3, 14)), VersionIV(..., VERSION_MIN)),
        (VersionIV((3, 10), (3, 14)), VersionIV(..., (3, 13))),
        (VersionIV((3, 10), (3, 14)), VersionIV((3, 11), ...)),
        (VersionIV((3, 10), (3, 14)), VersionIV((3, 10), (3, 12))),
        (VersionIV((3, 10), (3, 14)), VersionIV((3, 12), (3, 14))),
    ],
)
def test_setdiff(iv1: VersionIV, iv2: VersionIV):
    assert iv1 - iv2
    assert not (iv1 & iv2) - iv2
    assert iv1 - (iv1 & iv2) == iv1 - iv2
    assert (iv1 | iv2) - iv2 == iv1 - iv2
    assert (iv1 - iv2) | (iv1 & iv2) == iv1
