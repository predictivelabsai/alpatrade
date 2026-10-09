from fasthtml.common import to_xml

from engine.web.ph_landing import home_page


def test_hero_how_it_works_primer_and_name_note():
    h = to_xml(home_page())
    assert "Systematic trading" in h and "reimagined" in h
    assert "How it works?" in h and "Fine-tune the parameters with AI" in h
    for w in ("Signal", "Sizing", "Execution", "Dojima", "Bachelier", "Markowitz", "Turtles",
              "Renaissance", "Bridgewater", "explicit, testable rules"):
        assert w in h, w
    assert "अल्प" in h and "Why AlpaTrade?" in h and "Sanskrit for “little”" in h
    assert "It ties into the idea of small, disciplined edges compounding over time." in h
    assert h.index("reimagined") < h.index("id=\"why-alpatrade\"") < h.index("id=\"how-it-works\"")
    assert h.index("id=\"how-it-works\"") < h.index("id=\"hedge-funds\"")
