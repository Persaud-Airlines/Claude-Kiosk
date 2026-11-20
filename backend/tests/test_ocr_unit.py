"""Unit tests for name-extraction heuristics (engine independent)."""
from app.services.ocr import OcrLine, extract_names, parse_card_payload
from app.services.students import clean_person_name, normalize_name


def L(text, h=40, conf=0.95, y=0):
    return OcrLine(text=text, confidence=conf, height=h, y=y)


def test_label_split_fr():
    c = extract_names([L("Nom: TREMBLAY", y=10), L("Prénom: Émilie", y=60)])
    assert (c[0].first, c[0].last) == ("Émilie", "TREMBLAY")


def test_comma_layout():
    c = extract_names([L("LAKEVIEW SECONDARY SCHOOL", 30), L("Taylor, Jordan", 50, y=100)])
    assert (c[0].first, c[0].last) == ("Jordan", "Taylor")


def test_full_label_with_particle():
    c = extract_names([L("Student Name: Lucas De Silva")])
    assert (c[0].first, c[0].last) == ("Lucas", "De Silva")


def test_school_name_not_chosen():
    c = extract_names([L("Lakeview Secondary School", 50), L("Jordan Taylor", 45, y=100), L("Grade 11", 20, y=200)])
    assert (c[0].first, c[0].last) == ("Jordan", "Taylor")


def test_qr_payloads():
    assert parse_card_payload('{"first_name":"Ana","last_name":"Lopez","student_number":"123456"}')["last_name"] == "Lopez"
    assert parse_card_payload("Lopez,Ana,1234567") == {"last_name": "Lopez", "first_name": "Ana", "student_number": "1234567"}


def test_name_cleaning():
    assert clean_person_name("  o'BRIEN ") == "O'Brien"
    assert clean_person_name("mcdonald-SMITH") == "McDonald-Smith"
    assert normalize_name("Émilie", "Côté") == "emilie cote"
