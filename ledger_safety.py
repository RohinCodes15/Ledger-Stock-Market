"""Safety helpers for Ledger: password/PIN hashing, kid-safe name and headline checks.

Pure functions only (no pygame), so they can be unit-tested on their own:
    python -m unittest discover tests
"""
import hashlib
import hmac
import re
import secrets
import time

# ----------------------------
# PASSWORDS & PARENT PINS
# ----------------------------
# scrypt is a slow, salted hash built into Python. A stolen save file can't be reversed
# with a lookup table, and guessing is ~50ms per try instead of nanoseconds.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_secret(secret):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_secret(secret, stored):
    """Return (matches, needs_upgrade). Accepts scrypt hashes and the old unsalted SHA-256 hex."""
    if not stored:
        return False, False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt, digest = stored.split("$")
            test = hashlib.scrypt(secret.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                  dklen=len(digest) // 2)
        except (ValueError, TypeError):
            return False, False
        return hmac.compare_digest(test.hex(), digest), False
    if re.fullmatch(r"[0-9a-f]{64}", stored):
        legacy = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        ok = hmac.compare_digest(legacy, stored)
        return ok, ok
    return False, False


def pin_is_valid(pin):
    return bool(re.fullmatch(r"\d{4}", pin or ""))


class AttemptLimiter:
    """Slows down guessing: after `limit` misses, locks for `lock_seconds`."""

    def __init__(self, limit=5, lock_seconds=60):
        self.limit, self.lock_seconds = limit, lock_seconds
        self._misses = {}
        self._locked_until = {}

    def seconds_locked(self, key, now=None):
        now = time.time() if now is None else now
        return max(0, int(self._locked_until.get(key, 0) - now + 0.999))

    def miss(self, key, now=None):
        now = time.time() if now is None else now
        n = self._misses.get(key, 0) + 1
        if n >= self.limit:
            self._locked_until[key] = now + self.lock_seconds
            n = 0
        self._misses[key] = n

    def success(self, key):
        self._misses.pop(key, None)
        self._locked_until.pop(key, None)


# ----------------------------
# KID-SAFE TEXT
# ----------------------------
_LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a", "@": "a",
                       "5": "s", "$": "s", "7": "t", "+": "t", "8": "b", "9": "g"})

# Matched anywhere inside a name, even hidden in other letters ("xXslurXx").
# Only words that don't appear inside everyday words belong here.
_BLOCK_ANYWHERE = [
    "fuck", "fuk", "fck", "shit", "bitch", "cunt", "nigger", "nigga", "niga", "faggot", "fagot",
    "retard", "whore", "slut", "penis", "vagina", "porn", "dildo", "blowjob", "handjob", "horny",
    "nazi", "hitler", "kkk", "chink", "kike", "wetback", "tranny", "beaner", "twat", "bastard",
    "asshole", "jackass", "dumbass", "motherf", "molest", "orgasm", "cocaine",
    "suicide", "killyourself", "isgay", "isblack", "iswhite", "isfat", "isugly", "isdumb",
    "isstupid", "isretard", "isaloser", "sucks", "ihate", "jihad",
]
# Matched only as a whole word, because they hide inside innocent words
# (class, grape, hello, peacock, Dickens, raccoon, spice, title, Sussex...).
_BLOCK_WORDS = {
    "ass", "arse", "cum", "tit", "tits", "dick", "cock", "pussy", "sex", "sexy", "rape", "fag", "spic",
    "coon", "gook", "dyke", "hoe", "hoes", "damn", "hell", "crap", "piss", "weed", "drugs", "kill", "die",
    "nude", "naked", "thot", "stfu", "wtf", "milf", "anal", "kys", "isis", "negro", "pedo", "boob", "boobs",
    "heroin", "wank", "wanker",
}
_WORD_SPLIT = re.compile(r"[^a-z]+")


def _squash(text):
    """Lowercase, undo leetspeak, and collapse repeats: 'N1iiGG@' -> 'niga'."""
    text = text.lower().translate(_LEET)
    letters = re.sub(r"[^a-z]", "", text)
    return re.sub(r"(.)\1+", r"\1", letters), letters


def _squash_word(w):
    return re.sub(r"(.)\1+", r"\1", w)


# Squashed spellings catch "fuuuck"; very short squashed forms ("kkk" -> "k") would match everything.
_ANYWHERE_SQUASHED = {_squash_word(w) for w in _BLOCK_ANYWHERE if len(_squash_word(w)) >= 4}


def is_kid_safe(text):
    """False if the text contains profanity, slurs or bullying phrases."""
    if not text:
        return True
    squashed, letters = _squash(text)
    if any(w in letters or w in squashed for w in _BLOCK_ANYWHERE) or any(w in squashed for w in _ANYWHERE_SQUASHED):
        return False
    words = [w for w in _WORD_SPLIT.split(text.lower().translate(_LEET)) if w]
    # Also catch spaced-out spelling like "s e x".
    joined_singles = "".join(w for w in words if len(w) == 1)
    return not any(w in _BLOCK_WORDS or _squash_word(w) in _BLOCK_WORDS for w in words + [joined_singles])


def username_problem(name):
    """Return a kid-friendly reason the username can't be used, or None if it's fine."""
    name = " ".join((name or "").strip().split())
    if not 3 <= len(name) <= 14:
        return "Pick a username with 3 to 14 characters."
    if not re.fullmatch(r"[A-Za-z0-9 _.\-]+", name):
        return "Use only letters, numbers, spaces, _ . or -"
    if not re.search(r"[A-Za-z]", name):
        return "Your username needs at least one letter."
    if re.search(r"\d{5,}", name) or re.search(r"(www|\.com|\.net|\.org)", name, re.I):
        return "Keep phone numbers and websites out of your username."
    if not is_kid_safe(name):
        return "That username isn't allowed. Try something friendly!"
    return None


# Headlines about violence, crime or adult topics are skipped entirely on a kids' app.
_UNSAFE_HEADLINE_WORDS = {
    "kill", "killed", "kills", "killing", "murder", "murdered", "shooting", "shooter", "shot", "gun", "guns",
    "dead", "death", "deaths", "dies", "died", "suicide", "rape", "sexual", "sex", "porn", "abuse", "abused",
    "assault", "terror", "terrorist", "terrorism", "bomb", "bombing", "war", "wars", "massacre", "drug",
    "drugs", "cocaine", "opioid", "overdose", "fentanyl", "cannabis", "marijuana", "alcohol", "beer", "vodka",
    "whiskey", "gambling", "casino", "betting", "tobacco", "cigarette", "vape", "vaping", "crash", "hostage",
    "stabbing", "execution", "weapon", "weapons", "missile", "trafficking", "arrested", "prison",
}


def headline_is_kid_safe(title):
    words = set(_WORD_SPLIT.split((title or "").lower()))
    return not (words & _UNSAFE_HEADLINE_WORDS) and is_kid_safe(title)


# ----------------------------
# AGE
# ----------------------------
MIN_AGE_WITHOUT_PARENT = 13


def age_from_birth_year(year, today_year=None):
    today_year = today_year or int(time.strftime("%Y"))
    return today_year - int(year)


def birth_year_problem(text, today_year=None):
    today_year = today_year or int(time.strftime("%Y"))
    if not re.fullmatch(r"\d{4}", text or ""):
        return "Type the year you were born, like 2014."
    age = age_from_birth_year(text, today_year)
    if age < 5 or age > 110:
        return "Double-check that year."
    return None
