import unittest

from core.i18n import get_available_languages, get_language, set_language, t


class TestI18n(unittest.TestCase):
    def setUp(self):
        # Reset to default language before each test
        set_language("en")

    def tearDown(self):
        # Reset back to English after each test
        set_language("en")

    def test_available_languages(self):
        langs = get_available_languages()
        self.assertIn("en", langs)
        self.assertIn("it", langs)

    def test_set_and_get_language(self):
        self.assertTrue(set_language("it"))
        self.assertEqual(get_language(), "it")

        self.assertTrue(set_language("en"))
        self.assertEqual(get_language(), "en")

    def test_invalid_language_fallback(self):
        # Setting an unknown language should return False and fallback to English
        res = set_language("nonexistent_lang_code")
        self.assertFalse(res)
        self.assertEqual(get_language(), "en")

    def test_translation_lookup(self):
        set_language("en")
        en_val = t("cli.banner_subtitle")
        self.assertIn("CLI & Discord", en_val)
        self.assertIn("Chamber of Spirit and Time", en_val)

        set_language("it")
        it_val = t("cli.banner_subtitle")
        self.assertIn("CLI & Discord", it_val)
        self.assertIn("Stanza dello Spirito e del Tempo", it_val)
        self.assertNotEqual(en_val, it_val)

    def test_parameter_interpolation(self):
        set_language("en")
        interpolated = t("tasks.device_connected", serial="TEST_DEVICE", res="1080x1920")
        self.assertIn("TEST_DEVICE", interpolated)
        self.assertIn("1080x1920", interpolated)

    def test_missing_key_fallback_to_raw_key(self):
        unknown_key = "some.completely.unknown.nested.key"
        result = t(unknown_key)
        self.assertEqual(result, unknown_key)


if __name__ == "__main__":
    unittest.main()
