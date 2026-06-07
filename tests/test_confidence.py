from agent import confidence


def test_expresses_uncertainty():
    assert confidence.expresses_uncertainty("I'm not sure about this")
    assert confidence.expresses_uncertainty("I couldn't find that")
    assert not confidence.expresses_uncertainty("The capital is Paris.")


def test_annotate_low_confidence_adds_note():
    out = confidence.annotate("Acme raised $5M in 2021.", "low", "which funding round")
    assert "Low confidence" in out
    assert "which funding round?" in out


def test_annotate_noop_when_high_confidence():
    text = "Acme raised $5M."
    assert confidence.annotate(text, "high", "x") == text


def test_annotate_noop_when_already_hedged():
    text = "I'm not sure, but it might be $5M."
    assert confidence.annotate(text, "low", "what year") == text


def test_annotate_handles_empty():
    assert confidence.annotate("", "low", "q") == ""
