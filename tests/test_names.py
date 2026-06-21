from packages.shared.names import display_person_name, normalized_person_key


def test_display_person_name_orders_congress_names_for_reading():
    assert display_person_name("Crockett, Jasmine") == "Jasmine Crockett"
    assert display_person_name("Rep. Weber, Randy K. Sr. [R-TX-14]") == "Rep. Randy K. Weber Sr. [R-TX-14]"
    assert display_person_name("Sen. Hagerty, Bill [R-TN]") == "Sen. Bill Hagerty [R-TN]"


def test_normalized_person_key_handles_display_and_inverted_names():
    assert normalized_person_key("Cornyn, John") == normalized_person_key("John Cornyn")
