"""WCAG 2.x contrast of the page's palette, light and dark, read from app.css itself: 4.5 to 1 for every text
colour on every background it can sit on, and 3 to 1 for the borders, rings and bars that carry meaning."""
import os
import re
import unittest

from common_ground import web

TEXT_MIN = 4.5
SHAPE_MIN = 3.0
VAR = re.compile(r"^var\(--([a-z0-9-]+)\)$")
# Backgrounds a text colour set without its own background may land on, and the usual text colours a
# background set without its own colour carries.
AMBIENT = ("ground", "surface", "accent-wash")
USUAL_TEXT = ("ink", "muted")
# Backgrounds that hold no text: the bar fills and track, and the tick; the shapes test covers them.
NO_TEXT = ("bar-in", "bar-out", "track", "ink")
SHAPES = (
    ("line-strong", "surface"), ("line-strong", "ground"), ("focus", "surface"), ("focus", "ground"),
    ("bar-in", "track"), ("bar-out", "track"), ("bar-in", "surface"), ("ink", "track"),
)


def source():
    with open(os.path.join(web.WEB_DIR, "app.css"), encoding="utf-8") as fh:
        return re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)


def tokens(block):
    found = re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block)
    return {name: value.lower() for name, value in found}


def schemes(css):
    light = tokens(css[css.index(":root"):css.index("}", css.index(":root"))])
    start = css.index("@media (prefers-color-scheme: dark)")
    dark = tokens(css[start:css.index("}", css.index(":root", start))])
    return light, {**light, **dark}


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def rules(css):
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = dict(re.findall(r"([a-z-]+)\s*:\s*([^;]+);", body))
        yield selector.strip(), decls


def token_of(value):
    found = VAR.match(value.strip()) if value else None
    return found.group(1) if found else None


def text_pairs(css):
    """(selector, foreground token, background token) for every rule that sets a colour or a background."""
    pairs = []
    for selector, decls in rules(css):
        if selector.startswith(":root"):
            continue
        fg = token_of(decls.get("color"))
        bg = token_of(decls.get("background") or decls.get("background-color"))
        if fg and bg:
            pairs.append((selector, fg, bg))
        elif fg:
            pairs += [(selector, fg, ambient) for ambient in AMBIENT]
        elif bg and bg not in NO_TEXT:
            usual = ("on-hue",) if bg.startswith("hue-") else USUAL_TEXT
            pairs += [(selector, text, bg) for text in usual]
    return pairs


class Palette(unittest.TestCase):
    def setUp(self):
        self.css = source()
        self.light, self.dark = schemes(self.css)

    def test_every_token_the_stylesheet_uses_exists_in_both_schemes(self):
        used = set(re.findall(r"var\(--([a-z0-9-]+)\)", self.css)) - {"radius"}
        self.assertTrue(used)
        for scheme, palette in (("light", self.light), ("dark", self.dark)):
            self.assertEqual(used - set(palette), set(), scheme)

    def test_the_dark_scheme_redefines_the_surfaces_and_the_text(self):
        for name in ("ground", "surface", "ink", "muted", "accent", "track", "bar-in", "bar-out"):
            self.assertNotEqual(self.light[name], self.dark[name], name)

    def test_text_is_at_least_4_5_to_1_on_every_background_it_can_sit_on(self):
        pairs = text_pairs(self.css)
        self.assertGreater(len(pairs), 40)
        for scheme, palette in (("light", self.light), ("dark", self.dark)):
            for selector, fg, bg in pairs:
                with self.subTest(scheme=scheme, rule=selector, text=fg, on=bg):
                    self.assertGreaterEqual(ratio(palette[fg], palette[bg]), TEXT_MIN)

    def test_the_named_pairs_the_page_relies_on(self):
        named = (("ink", "ground"), ("ink", "surface"), ("muted", "ground"), ("muted", "surface"),
                 ("accent", "ground"), ("on-accent", "accent"), ("warn-ink", "warn-bg"),
                 ("alert-ink", "alert-bg"), ("good-ink", "good-bg"), ("alert-ink", "surface"),
                 ("on-hue", "hue-0"), ("on-hue", "hue-1"), ("on-hue", "hue-2"), ("on-hue", "hue-3"),
                 ("on-hue", "hue-4"), ("on-hue", "hue-5"))
        for scheme, palette in (("light", self.light), ("dark", self.dark)):
            for fg, bg in named:
                with self.subTest(scheme=scheme, text=fg, on=bg):
                    self.assertGreaterEqual(ratio(palette[fg], palette[bg]), TEXT_MIN)

    def test_borders_rings_and_bars_are_at_least_3_to_1(self):
        for scheme, palette in (("light", self.light), ("dark", self.dark)):
            for shape, bg in SHAPES:
                with self.subTest(scheme=scheme, shape=shape, on=bg):
                    self.assertGreaterEqual(ratio(palette[shape], palette[bg]), SHAPE_MIN)


class Motion(unittest.TestCase):
    def test_reduced_motion_switches_every_animation_and_transition_off(self):
        css = source()
        reduce = css[css.index("@media (prefers-reduced-motion: reduce)"):]
        reduce = reduce[:reduce.index("\n}\n")]
        for name in ("animation-duration", "transition-duration", "scroll-behavior"):
            self.assertIn(name, reduce)

    def test_nothing_moves_outside_the_no_preference_block(self):
        css = source()
        start = css.index("@media (prefers-reduced-motion: no-preference)")
        block = css[start:css.index("\n}\n", start)]
        moving = re.findall(r"\b(?:transition|animation)\s*:", css)
        self.assertEqual(len(moving), len(re.findall(r"\b(?:transition|animation)\s*:", block)))


if __name__ == "__main__":
    unittest.main()
