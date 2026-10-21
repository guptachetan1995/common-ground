"""The fixed sentences are in web/ word for word: the public-things hint beside each person's favourite
boxes, the mode banners and the two banners that say why the person gate cannot work."""
import os
import re
import unittest

from common_ground import web


def source(name):
    with open(os.path.join(web.WEB_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def flat(text):
    return " ".join(text.split())


class FixedSentences(unittest.TestCase):
    def test_the_public_things_hint_sits_with_every_persons_favourite_boxes(self):
        hint = (
            "Type the names of public things only (a restaurant, a band, a film, a show, a book, a brand). "
            "Each name is sent to Qloo to find a match."
        )
        template = source("index.html")
        template = template[template.index("<template"):template.index("</template>")]
        self.assertIn(hint, flat(template))
        self.assertEqual(len(re.findall(r'class="p-fav"', template)), 3)
        self.assertIn('input.setAttribute("aria-describedby", hint.id)', source("app.js"))

    def test_the_mode_banners(self):
        script = flat(source("app.js"))
        self.assertIn('live: "Live: Qloo is being called"', script)
        self.assertIn('synthetic: "Synthetic sample data. Qloo is not being called."', script)
        self.assertIn("Daily ceiling spent:", script)
        self.assertIn("(key: ${mode.key})", script)

    def test_the_two_gate_banners(self):
        script = flat(source("app.js"))
        self.assertIn("your browser sends no label with its requests, and Resolve, Pick and Sign off cannot "
                      "work here. Open the HTTPS address.", script)
        self.assertIn("Your browser does not label requests, so you cannot resolve a match or sign off here. "
                      "Use a current Chrome, Firefox or Safari.", script)
        self.assertIn("because its own address is https", script)

    def test_the_ceiling_has_a_banner_for_a_sample_outing_and_another_for_one_opened_live(self):
        script = flat(source("app.js"))
        self.assertIn('ceilingSample: "Daily ceiling spent: showing synthetic sample data."', script)
        self.assertIn("This outing was opened after the server used its live Qloo calls for the day, so its "
                      "places are invented and Qloo is not being called for it.", script)
        self.assertIn("live Qloo calls are refused for this outing until the day changes (UTC) or the server "
                      "restarts. It is never switched to sample data.", script)
        self.assertIn("A new outing runs on synthetic sample data, labelled as such.", script)
        self.assertIn('outing && outing.source === "synthetic"', script)

    def test_the_board_says_whose_each_figure_is_and_what_the_bar_and_the_tick_mean(self):
        script = flat(source("app.js"))
        for sentence in (
            "Each bar is one person's own ranking of the ${size} places: the longer the bar, the higher "
            "${view.who} ranks the place for that person's favourites.",
            "The tick marks the half-way line, this app's rule for the upper half.",
            "Scores from separate calls are not comparable between people.",
            "${entry.affinity.toFixed(2)} on ${member.name}'s own scale", '"affinity"',
            "Qloo's band", "ranks it ${entry.rank} of ${view.size}", "Qloo gave no figure",
            "outside their upper half",
            "Qloo's figures describe how its audiences relate to the things a person named. They are not a "
            "prediction about that person.",
            "That is this app's rule, not Qloo's.",
            "sentence(c.chance)",
        ):
            with self.subTest(sentence[:50]):
                self.assertIn(sentence, script)

    def test_the_results_say_each_outcome_in_words(self):
        script = flat(source("app.js"))
        for sentence in (
            "No place is shared by everyone. The closest places below name who each one leaves out.",
            "No place comes close: ${who} ranked only part of the long list",
            "Too few places came back to compare people, so nothing was ranked.",
            "${capital(view.who)} ranked only ${got.ranked} of ${got.of} places for ${names[id]}.",
            "returned an order without affinity figures, so none is shown.",
            "Qloo found nothing for “${favourite.name}”, so it is not used.",
            "has not been searched yet, so it is not used.",
            "The matches or conditions changed after this comparison, so it is out of date. Compare again.",
            "This outing has used all ${b.limit} of its Qloo calls. Only you can raise the limit",
            "so a place shown here as common may still leave them out.",
        ):
            with self.subTest(sentence[:50]):
                self.assertIn(sentence, script)

    def test_a_message_is_a_draft_until_signed_off_and_the_page_never_says_it_sends_anything(self):
        script = flat(source("app.js"))
        self.assertIn("This app never sends a message, books a table or pays anyone. You send it yourself.",
                      script)
        self.assertIn("Signing off removes the DRAFT line.", script)
        self.assertIn('text: released ? `Signed off by ${draft.signedOffBy}` : "DRAFT"', script)
        self.assertIn("No recipient is filled in.", script)
        self.assertIn("A favourite is named only where the person matched it themself.", script)
        self.assertIn("Name the sender before signing a message off.", script)
        self.assertNotRegex(script, r"(?i)\b(sent to the group|booked!|reservation confirmed)")

    def test_the_add_a_favourite_box_carries_the_public_things_sentence_on_both_pages(self):
        script = flat(source("app.js"))
        sentence = ("Type the names of public things only (a restaurant, a band, a film, a show, a book, "
                    "a brand). Each name is sent to Qloo to find a match.")
        self.assertIn(f'publicThings: "{sentence}"', script)
        self.assertIn('id: `${id}-hint`, text: SENTENCES.publicThings', script)
        self.assertIn('"aria-describedby": `${id}-hint`', script)
        self.assertIn("Add a favourite of your own", script)
        self.assertIn("Add a favourite for ${member.name}", script)

    def test_the_organisers_label_is_the_phrase_the_readme_uses(self):
        self.assertIn("resolved by the organiser for ${member.name}", source("app.js"))

    def test_the_page_says_what_a_restart_does_and_claims_no_lifetime(self):
        for name in ("index.html", "app.js"):
            text = flat(source(name))
            with self.subTest(name):
                self.assertNotRegex(text, r"(?i)hours of inactivity|idle timeout|7200|two hours")
        self.assertIn("a free host stops after 15 minutes without traffic, takes up to a minute to wake, and "
                      "wakes empty", flat(source("index.html")))
        self.assertIn("a restart empties every workspace", flat(source("app.js")))

    def test_the_page_names_no_price_availability_or_liking_claim(self):
        for name in ("index.html", "member.html", "app.js"):
            text = source(name)
            with self.subTest(name):
                claims = r"(?i)open now|a table is available|has a table|guaranteed|everyone agrees"
                self.assertIsNone(re.search(claims, text))
                self.assertIsNone(re.search(r"(?i)will (like|love|enjoy)", text))


if __name__ == "__main__":
    unittest.main()
