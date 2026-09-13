import pytest
from src.tools.email.ml_classifier import MLEmailClassifier, _build_feature_text


def test_ml_classifier_loads():
    ml = MLEmailClassifier.get_instance()
    assert ml.load() is True
    assert ml.is_available() is True
    meta = ml.get_metadata()
    assert "accuracy" in meta
    assert meta["accuracy"] >= 0.75
    assert "classes" in meta
    assert "rejection" in meta["classes"]
    assert "application_confirmation" in meta["classes"]


def test_ml_classifier_predict_rejection():
    ml = MLEmailClassifier.get_instance()
    result = ml.predict(
        subject="Ihre Bewerbung als Software Engineer",
        body="Wir bedauern Ihnen mitteilen zu müssen, dass wir Ihre Bewerbung für die Position leider nicht berücksichtigen können.",
        sender_email="recruiting@company.de",
    )
    assert result is not None
    assert result.category == "rejection"
    assert result.confidence > 0.35
    assert "ML classifier" in result.explanation


def test_ml_classifier_predict_confirmation():
    ml = MLEmailClassifier.get_instance()
    result = ml.predict(
        subject="Eingangsbestätigung Ihrer Bewerbung",
        body="Vielen Dank für Ihre Bewerbung und Ihr Interesse an einer Mitarbeit in unserem Unternehmen.",
        sender_email="karriere@unternehmen.de",
    )
    assert result is not None
    assert result.category == "application_confirmation"
    assert result.confidence > 0.35


def test_ml_classifier_build_feature_text():
    feat = _build_feature_text("Software Engineer", "Body preview text here", "jobs@ashbyhq.com")
    assert "Software Engineer" in feat
    assert "ashbyhq" in feat
    assert "Body preview" in feat
