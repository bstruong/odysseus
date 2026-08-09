"""Regression: the agent tool-RAG domain classifier's `email` domain only
matched literal email vocabulary ("email"/"mail"/"gmail"/"inbox"/...) plus
three hardcoded names lifted from one earlier repro ("message chris|message
him|message her"). A neutral, keyword-free prompt about a real, specific
email — e.g. "Do I have anything from A3 Tech Group about a partnership for
my saber project?" — matched no domain, was flagged low_signal, and tool
retrieval was skipped entirely: the model got zero email-flavored tools and
correctly (given what it was handed) reported it had no way to check.

Root cause: `_classify_agent_request` in src/agent_loop.py sets
`low_signal = not continuation and not domains`; the `email` domain regex
required literal email words or one of three hardcoded names, so ordinary
correspondence-inquiry phrasing (no "email"/"mail"/"inbox" anywhere) fell
through to no domain -> low_signal -> retrieval skipped.

The classifier is deterministic string matching (no embeddings / no DB), so
it can be exercised directly, same as test_tool_rag_contacts_domain.py.
"""

from src.agent_loop import _classify_agent_request


def _classify(text):
    return _classify_agent_request([{"role": "user", "content": text}], text)


def test_correspondence_inquiry_prompts_get_email_domain_without_email_keywords():
    """Neutral prompts about a real message someone sent must match the
    `email` domain and NOT be low_signal, even with no literal
    email/mail/inbox word anywhere in the text."""
    prompts = [
        "Do I have anything from A3 Tech Group about a partnership for my saber project?",
        "Did I hear back from the landlord about the lease renewal?",
        "Has Sara reached out about the invoice yet?",
        "Did the vendor contact us about the shipment delay?",
        "Did Alex ever get back to me about Friday?",
        "Did Priya follow up on the budget proposal?",
        "Message Chris and see if he replied about the trip.",
        "Did the recruiter write to me about next steps?",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "email" in intent["domains"], f"expected email domain for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_literal_email_keyword_prompts_still_match_email_domain():
    """Regression check: prompts that previously worked via literal
    "email"/"mail"/"inbox" wording must keep working after widening the
    signal — this is not a replacement for the keyword list, an addition."""
    prompts = [
        "Check my email for anything from support.",
        "Search my inbox for the receipt.",
        "Reply to the latest email from Dana.",
        "Forward that email to my accountant.",
        "Draft an email to the team about Monday.",
    ]
    for p in prompts:
        intent = _classify(p)
        assert "email" in intent["domains"], f"expected email domain for: {p!r}"
        assert intent["low_signal"] is False, f"must not be low_signal: {p!r}"


def test_unrelated_requests_do_not_match_email_domain():
    """Guard against over-triggering: ordinary non-correspondence prompts
    must not be flagged email."""
    assert "email" not in _classify("what is the capital of France")["domains"]
    assert "email" not in _classify("what's 2 plus 2")["domains"]
    assert "email" not in _classify("generate an image of a sunset")["domains"]
    assert "email" not in _classify("what time is it in Tokyo")["domains"]
