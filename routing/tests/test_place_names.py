"""Unit tests for the shared place-name normaliser."""

from django.test import SimpleTestCase

from routing.services.place_names import coord_key, normalize_place


class PlaceNameTests(SimpleTestCase):
    def test_strips_census_place_descriptors(self):
        self.assertEqual(normalize_place("Abbeville city"), "abbeville")
        self.assertEqual(normalize_place("Barrington town"), "barrington")
        self.assertEqual(normalize_place("Abanda CDP"), "abanda")
        self.assertEqual(normalize_place("Somewhere borough"), "somewhere")

    def test_handles_census_balance_suffix(self):
        self.assertEqual(normalize_place("Louisville city (balance)"), "louisville")

    def test_reconciles_csv_and_gazetteer_spellings(self):
        self.assertEqual(normalize_place("Bois D'Arc"), normalize_place("bois d arc"))
        self.assertEqual(normalize_place("Mc Graw"), "mc graw")

    def test_does_not_strip_real_name_words(self):
        # "City" only disappears when it is the trailing descriptor token.
        self.assertEqual(normalize_place("Kansas City"), "kansas")

    def test_coord_key_is_normalised_and_uppercased(self):
        self.assertEqual(coord_key("Big Cabin", "ok"), "big cabin|OK")
        self.assertEqual(coord_key("Saint Louis ", " mo "), "saint louis|MO")
