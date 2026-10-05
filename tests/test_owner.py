import pytest

from smoothment.classify.owner import OwnerMatcher
from smoothment.config import OwnerSettings

MATCHER = OwnerMatcher(OwnerSettings(names=["Sample Owner", "Сэмпл О."], phones=["0070000000000"]))


@pytest.mark.parametrize(
    "text",
    [
        "PARTNER PERSON & SAMPLE OWNER",
        "Sample owner",
        "Owner, Sample",
    ],
)
def test_is_owner_matches(text: str) -> None:
    assert MATCHER.is_owner(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Sample Ownerson",
        "Sam Owner",
    ],
)
def test_is_owner_does_not_match(text: str) -> None:
    assert MATCHER.is_owner(text) is False


def test_is_owner_matches_cyrillic_name_with_one_letter_surname_token() -> None:
    assert MATCHER.is_owner("Перевод от Сэмпл О.") is True


def test_is_owner_none_never_matches() -> None:
    assert MATCHER.is_owner(None) is False


def test_is_owner_empty_text_never_matches() -> None:
    assert MATCHER.is_owner("") is False


def test_mentions_phone_found_inside_description() -> None:
    text = ".../СБП/2026-09-14 11:14:31/0070000000000/B625..."
    assert MATCHER.mentions_phone(text) is True


def test_mentions_phone_absent() -> None:
    assert MATCHER.mentions_phone("no phone here") is False


def test_mentions_phone_none_never_matches() -> None:
    assert MATCHER.mentions_phone(None) is False
