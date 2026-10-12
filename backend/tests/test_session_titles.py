import pytest

from app.services.session_titles import generate_session_title, is_default_session_title


@pytest.mark.parametrize(("message", "expected"), [
    ("How to Find Product-Market Fit", "Finding Product-Market Fit"),
    ("What are the best ways to improve user onboarding?", "Improving User Onboarding"),
    ("Explain startup growth loops with examples", "Understanding Startup Growth Loops"),
    ("Help me write a Ship 30 essay about product growth", "Writing an Essay on Product Growth"),
    ("What did Lenny say about retention?", "Lenny’s Lessons on Retention"),
    ("How can I validate my startup idea?", "Validating a Startup Idea"),
    ("What are common mistakes product managers make?", "Common Mistakes Product Managers Make"),
])
def test_generates_concise_descriptive_titles(message, expected):
    title = generate_session_title(message)
    assert title == expected
    assert len(title) <= 50
    assert 3 <= len(title.split()) <= 7


@pytest.mark.parametrize("message", ["", "Hi", "Hello there!", "Thanks", "Okay."])
def test_greetings_do_not_replace_the_default_title(message):
    assert generate_session_title(message) is None


def test_removes_credential_and_contact_details_from_titles():
    title = generate_session_title("Ask about retention; email jane@example.com, password=Secret123, phone +1 555-555-0182")
    assert title == "Retention"
    assert "jane" not in title.lower()
    assert "secret" not in title.lower()
    assert "555" not in title


def test_long_message_is_bounded_and_markdown_is_removed():
    title = generate_session_title("**Explain** startup growth loops with examples and many additional details about acquisition and activation")
    assert title == "Understanding Startup Growth Loops"
    assert len(title) <= 50


def test_default_title_matching_is_case_insensitive_and_preserves_custom_names():
    assert is_default_session_title(" New CHAT ")
    assert not is_default_session_title("Finding Product-Market Fit")
