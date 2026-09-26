import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ledger_safety as ls  # noqa: E402


class PasswordTests(unittest.TestCase):
    def test_scrypt_roundtrip_and_salt(self):
        a, b = ls.hash_secret("hunter22"), ls.hash_secret("hunter22")
        self.assertNotEqual(a, b)  # salted
        self.assertEqual(ls.verify_secret("hunter22", a), (True, False))
        self.assertEqual(ls.verify_secret("wrong", a), (False, False))

    def test_legacy_sha256_matches_and_asks_for_upgrade(self):
        old = hashlib.sha256(b"pass1234").hexdigest()
        self.assertEqual(ls.verify_secret("pass1234", old), (True, True))
        self.assertEqual(ls.verify_secret("nope", old), (False, False))

    def test_empty_or_garbage_hash_never_matches(self):
        self.assertEqual(ls.verify_secret("", ""), (False, False))
        self.assertEqual(ls.verify_secret("x", "scrypt$bad"), (False, False))

    def test_pin(self):
        self.assertTrue(ls.pin_is_valid("0420"))
        for bad in ("", "123", "12345", "12a4"):
            self.assertFalse(ls.pin_is_valid(bad))

    def test_attempt_limiter_locks_then_unlocks(self):
        lim = ls.AttemptLimiter(limit=3, lock_seconds=60)
        for _ in range(3):
            lim.miss("kid", now=100)
        self.assertEqual(lim.seconds_locked("kid", now=100), 60)
        self.assertEqual(lim.seconds_locked("kid", now=161), 0)


class UsernameTests(unittest.TestCase):
    def test_normal_names_allowed(self):
        for name in ["StockNinja", "rohinxtrades", "alex_thebull", "trader1", "Glass Cannon", "Scarlett",
                     "Hello Kitty", "Grape Ape", "Peacock22", "Class Clown", "Dickens Fan", "Sky Rocket",
                     "Skyscraper", "Title Wave", "Cocktail Pro", "Raccoon Kid", "Spice Trader", "Torpedo",
                     "Crisis Pro", "Swanky", "Superheroine", "Night Owl", "Assassin", "Hancock", "Pass Go"]:
            self.assertIsNone(ls.username_problem(name), name)

    def test_offensive_names_blocked(self):
        for name in ["nigga", "N1GGA", "niiigga", "khsitijisblack", "fuuuck", "sh1t_head", "ur a b1tch",
                     "s e x", "kys", "KKK fan", "xXhitlerXx", "joe is gay", "Nazi_boi", "dumbass"]:
            self.assertIsNotNone(ls.username_problem(name), name)

    def test_shape_rules(self):
        self.assertIsNotNone(ls.username_problem("ab"))
        self.assertIsNotNone(ls.username_problem("a" * 15))
        self.assertIsNotNone(ls.username_problem("12345"))            # no letter
        self.assertIsNotNone(ls.username_problem("call 5551234"))     # phone number
        self.assertIsNotNone(ls.username_problem("me@mail"))          # email-ish / symbol
        self.assertIsNotNone(ls.username_problem("rohin#3024"))
        self.assertIsNotNone(ls.username_problem("www.me.com"))


class HeadlineTests(unittest.TestCase):
    def test_filter(self):
        self.assertTrue(ls.headline_is_kid_safe("Apple beats earnings estimates on strong iPhone demand"))
        self.assertFalse(ls.headline_is_kid_safe("Shooting at plant halts production"))
        self.assertFalse(ls.headline_is_kid_safe("Brewer launches new vodka line"))


class AgeTests(unittest.TestCase):
    def test_birth_year(self):
        self.assertIsNone(ls.birth_year_problem("2014", today_year=2026))
        self.assertEqual(ls.age_from_birth_year("2014", today_year=2026), 12)
        self.assertIsNotNone(ls.birth_year_problem("14", today_year=2026))
        self.assertIsNotNone(ls.birth_year_problem("2025", today_year=2026))


if __name__ == "__main__":
    unittest.main()
