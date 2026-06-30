"""Normalizer unit tests, including the garbage-in -> None edge cases."""

from transformer.normalize.phones import normalize_phone
from transformer.normalize.dates import normalize_date, normalize_year
from transformer.normalize.location import normalize_country, normalize_location
from transformer.normalize.skills import normalize_skill
from transformer.normalize.emails import normalize_email, normalize_emails


def test_phone_e164():
    assert normalize_phone("+1 415-555-0132") == "+14155550132"
    assert normalize_phone("(415) 555-0132") == "+14155550132"  # default region US


def test_phone_garbage_is_none():
    assert normalize_phone("not-a-number") is None
    assert normalize_phone("N/A") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_dates():
    assert normalize_date("2021-03") == "2021-03"
    assert normalize_date("03/2021") == "2021-03"
    assert normalize_date("March 2021") == "2021-03"
    assert normalize_date("2021") == "2021"          # year-only stays year-only
    assert normalize_date("present") is None          # open-ended
    assert normalize_date("sometime 2021") is None    # unparseable -> None
    assert normalize_year("MIT, 2017") is None        # only clean values parse
    assert normalize_year("2017") == 2017


def test_country_iso():
    assert normalize_country("USA") == "US"
    assert normalize_country("United States") == "US"
    assert normalize_country("United Kingdom") == "GB"
    assert normalize_country("Atlantis") is None


def test_location_freetext():
    loc = normalize_location("San Francisco, CA, USA")
    assert loc == {"city": "San Francisco", "region": "CA", "country": "US"}


def test_skill_canonicalization():
    assert normalize_skill("reactjs") == "React"
    assert normalize_skill("React.js") == "React"
    assert normalize_skill("golang") == "Go"
    assert normalize_skill("k8s") == "Kubernetes"
    # unknown but real skill is kept, never invented away
    assert normalize_skill("Rust") == "Rust"


def test_emails():
    assert normalize_email("  Jane.Doe@Example.com ") == "jane.doe@example.com"
    assert normalize_email("not-an-email") is None
    assert normalize_emails(["a@b.com", "a@b.com", "bad"]) == ["a@b.com"]
