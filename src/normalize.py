"""
Shared Bangla text normalizer.

The SAME normalization is applied to the ground truth and to every model's
hypothesis before scoring. This is what makes WER/CER comparable across
providers -- naive scoring swings 10-20% purely on ZWNJ / danda / digit
handling, so all of it is neutralized here.
"""
import re
import unicodedata

# Bangla digits -> ASCII (pick one representation so "১০" == "10")
_BANGLA_DIGITS = "০১২৩৪৫৬৭৮৯"
_ASCII_DIGITS = "0123456789"
_DIGIT_MAP = {ord(b): a for b, a in zip(_BANGLA_DIGITS, _ASCII_DIGITS)}

# Zero-width joiners are inserted inconsistently by different engines.
_ZERO_WIDTH = dict.fromkeys([0x200C, 0x200D, 0xFEFF], None)  # ZWNJ, ZWJ, BOM

# Punctuation to strip (Bangla danda + English/quotes/brackets/etc.)
_PUNCT = re.compile(
    r"[।॥,.?!;:\"'`’‘“”…\-—–_/\\|()\[\]{}<>@#$%^&*+=~•]"
)

_WS = re.compile(r"\s+")


def normalize(text) -> str:
    if text is None:
        return ""
    t = unicodedata.normalize("NFC", str(text))
    t = t.translate(_ZERO_WIDTH)   # drop zero-width chars
    t = t.translate(_DIGIT_MAP)    # Bangla digits -> ASCII
    t = _PUNCT.sub(" ", t)         # remove punctuation
    t = t.lower()                  # only affects any Latin tokens
    t = _WS.sub(" ", t).strip()    # collapse whitespace
    return t


if __name__ == "__main__":
    # Quick self-check on tricky cases.
    samples = [
        ("আমি ১০টা বই পড়েছি।", "আমি 10টা বই পড়েছি"),
        ("বাংলা‌দেশ",       "বাংলাদেশ"),
        ("হ্যালো,  world!",      "হ্যালো world"),
    ]
    for raw, expected in samples:
        got = normalize(raw)
        flag = "ok" if got == expected else "MISMATCH"
        print(f"[{flag}] {raw!r} -> {got!r}")
