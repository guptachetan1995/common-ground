import copy
import re
import unittest

from common_ground import drafts, outings
from tests.test_outings import candidates, counter, refused, sample_args


def resolved_outing(resolver=None, favourites_per_member=None, when="Fri 6 Nov, 7:30 pm", names=None,
                    source=outings.LIVE):
    """The sample outing with every favourite searched and resolved. `resolver` maps a favourite id to who
    resolved it (default: each member did)."""
    token = counter()
    doc, ws = outings.add_workspace(outings.new_doc(), token=token, now=0.0)
    args = {**sample_args(), "when": when}
    if names:
        args["members"] = [{"name": n, "favourites": f} for n, f in names]
    doc, out = outings.open_outing(doc, ws, args, token=token, now=0.0, source=source)
    for m in outings.outing(doc, ws, out)["members"]:
        for f in m["favourites"]:
            doc = outings.store_candidates(doc, ws, out, m["id"], f["id"], candidates(f["id"]))
            by = (resolver or {}).get(f["id"], "member")
            doc = outings.resolve(doc, ws, out, m["id"], f["id"], f"cand-{f['id']}", by)
    return outings.outing(doc, ws, out)


def place(out, left_out=(), because=None, name="Alder Table"):
    """A place doc in the shape the outing document stores. `because` maps a member id to the favourite that
    explains the place for them; by default each member's first favourite does."""
    members = []
    for m in out["members"]:
        if because is None:
            lines = [{"favourite": m["favourites"][0]["id"], "score": 0.4}]
        elif m["id"] in because:
            lines = [{"favourite": because[m["id"]], "score": 0.5}]
        else:
            lines = []
        members.append({"member": m["id"], "rank": 3, "affinity": 0.7, "band": "High",
                        "inUpperHalf": m["id"] not in left_out, "because": lines, "ranked": True,
                        "restsOnOrganiserResolution": False})
    return {"entityId": "p1", "name": name, "listPosition": 1, "status": "common", "perMember": members,
            "placedBy": "worst_rank"}


def words(text):
    return len(text.split())


class Invitation(unittest.TestCase):
    def test_a_draft_reads_draft_and_asks_for_a_sender(self):
        out = resolved_outing()
        draft = drafts.make_draft(out, place(out), "invitation", "d1", 7)
        lines = draft["text"].split("\n")
        self.assertEqual(lines[0], drafts.DRAFT_LINE)
        self.assertEqual(lines[0], "DRAFT. Not signed off. Do not send.")
        self.assertEqual(lines[-1], "[sender name needed]")
        fields = ("state", "signedOffBy", "kind", "placeId", "revision")
        self.assertEqual([draft[f] for f in fields], ["draft", None, "invitation", "p1", 7])

    def test_the_invitation_follows_the_template(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out), "invitation", "d1", 1)["text"]
        self.assertEqual(text, (
            "DRAFT. Not signed off. Do not send.\n"
            "Hi all. I'm suggesting Alder Table for Fri 6 Nov, 7:30 pm. Why this one: Qloo's taste data, "
            "which I used to find it, connects it to Noor's Lost in Translation, Owen's The Bear, "
            "Pia's Patagonia and Quinn's Katz's Delicatessen. Nothing is booked.\n"
            "Tell me if it doesn't work for you, and what would.\n"
            "[sender name needed]"
        ))

    def test_a_sample_outing_never_credits_qloo(self):
        out = resolved_outing(source=outings.SYNTHETIC)
        text = drafts.make_draft(out, place(out), "invitation", "d1", 1)["text"]
        self.assertIn("Why this one: sample taste data, standing in for Qloo's, connects it to Noor's", text)
        self.assertNotIn("Qloo's taste data", text)
        upper_half = drafts.make_draft(out, place(out, because={}), "invitation", "d1", 1)["text"]
        self.assertIn("as the sample data orders them", upper_half)
        pia_out = place(out, left_out=("m3",), because={})
        left_out = drafts.make_draft(out, pia_out, "invitation", "d1", 1)["text"]
        self.assertIn("One caveat: the sample data ranks it outside the upper half for Pia.", left_out)
        self.assertIn("Why this one: the sample data ranks it in the upper half for", left_out)

    def test_without_a_when_the_day_is_used(self):
        out = resolved_outing(when=None)
        text = drafts.make_draft(out, place(out), "invitation", "d1", 1)["text"]
        self.assertIn("I'm suggesting Alder Table for Friday.", text)

    def test_without_explainability_the_evidence_is_the_upper_half(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out, because={}), "invitation", "d1", 1)["text"]
        self.assertIn(
            "Why this one: it sits in the upper half of each of our rankings, as Qloo orders them. "
            "Nothing is booked.",
            text,
        )
        self.assertNotIn("taste data", text)

    def test_a_favourite_the_organiser_resolved_is_never_named(self):
        out = resolved_outing(resolver={"f3": "organiser_for", "f4": "organiser_for"})
        text = drafts.make_draft(out, place(out), "invitation", "d1", 1)["text"]
        self.assertIn("Owen's favourites", text)
        self.assertNotIn("The Bear", text)
        self.assertIn("Noor's Lost in Translation", text)

    def test_only_the_favourite_that_explains_the_place_is_named_and_only_if_the_member_resolved_it(self):
        out = resolved_outing(resolver={"f3": "organiser_for"})
        by_member = place(out, because={"m2": "f4"})
        self.assertIn("Owen's Dune", drafts.make_draft(out, by_member, "invitation", "d1", 1)["text"])
        by_organiser = place(out, because={"m2": "f3"})
        text = drafts.make_draft(out, by_organiser, "invitation", "d1", 1)["text"]
        self.assertIn("Owen's favourites", text)
        self.assertNotIn("The Bear", text)

    def test_the_top_line_per_member_wins(self):
        out = resolved_outing()
        crowd = place(out, because={"m1": "f2"})
        crowd["perMember"][0]["because"] = [
            {"favourite": "f1", "score": 0.3}, {"favourite": "f2", "score": 0.9}
        ]
        self.assertIn("Noor's Khruangbin", drafts.make_draft(out, crowd, "invitation", "d1", 1)["text"])

    def test_anyone_left_out_is_named(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out, left_out=("m3",)), "invitation", "d1", 1)["text"]
        self.assertIn("One caveat: Qloo ranks it outside the upper half for Pia. Nothing is booked.", text)
        two = drafts.make_draft(out, place(out, left_out=("m2", "m4")), "invitation", "d1", 1)["text"]
        self.assertIn("outside the upper half for Owen and Quinn.", two)
        three = drafts.make_draft(out, place(out, left_out=("m1", "m2", "m4")), "invitation", "d1", 1)["text"]
        self.assertIn("for Noor, Owen and Quinn.", three)

    def test_when_someone_is_left_out_the_fallback_does_not_claim_everyone_is_inside(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out, left_out=("m3",), because={}), "invitation", "d1", 1)["text"]
        self.assertIn("Why this one: Qloo ranks it in the upper half for Noor, Owen and Quinn.", text)
        self.assertNotIn("each of our rankings", text)

    def test_no_caveat_when_nobody_is_left_out(self):
        out = resolved_outing()
        self.assertNotIn("caveat", drafts.make_draft(out, place(out), "invitation", "d1", 1)["text"])


class BookingRequest(unittest.TestCase):
    def test_the_template(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out), "booking_request", "d2", 1)["text"]
        self.assertEqual(text, (
            "DRAFT. Not signed off. Do not send.\n"
            "Hello. I'm asking whether you have space for 4 people on Fri 6 Nov, 7:30 pm, "
            "and what the options are.\n"
            "This message is not a booking and makes no offer.\n"
            "[sender name needed]"
        ))

    def test_neither_message_names_a_price_a_table_or_an_availability(self):
        out = resolved_outing(when=None)
        for kind in drafts.KINDS:
            text = drafts.make_draft(out, place(out, left_out=("m2",)), kind, "d", 1)["text"].lower()
            with self.subTest(kind=kind):
                banned = r"[$£€]|price|availab|table is|reserved|confirmed|pay|deposit"
                self.assertIsNone(re.search(banned, text))

    def test_a_kind_must_be_known(self):
        out = resolved_outing()
        self.assertEqual(
            refused(drafts.make_draft, out, place(out), "newsletter", "d", 1), ("bad_arguments", "kind")
        )


class SigningOff(unittest.TestCase):
    def setUp(self):
        self.out = resolved_outing()
        self.draft = drafts.make_draft(self.out, place(self.out), "invitation", "d1", 3)

    def test_release_drops_the_draft_line_and_names_the_sender(self):
        released = drafts.release(self.draft, "Noor", 4)
        self.assertNotIn("DRAFT", released["text"])
        self.assertEqual(released["text"].split("\n")[-1], "Noor")
        self.assertEqual(
            (released["state"], released["signedOffBy"], released["revision"]), ("released", "Noor", 4)
        )
        self.assertEqual(self.draft["state"], "draft")
        self.assertIn("DRAFT", self.draft["text"])

    def test_a_sender_is_needed(self):
        for sender in (None, "", "   ", "\n", 5):
            with self.subTest(sender=sender):
                self.assertEqual(refused(drafts.release, self.draft, sender, 4)[0], "sender_missing")

    def test_a_sender_is_one_tidy_line_of_at_most_sixty_characters(self):
        self.assertEqual(drafts.release(self.draft, "  Noor \n Hale ", 4)["signedOffBy"], "Noor Hale")
        self.assertEqual(refused(drafts.release, self.draft, "n" * 61, 4)[0], "bad_arguments")
        self.assertEqual(drafts.release(self.draft, "n" * 60, 4)["signedOffBy"], "n" * 60)

    def test_the_released_text_comes_from_the_snapshot_alone(self):
        later = copy.deepcopy(self.out)
        later["members"][0]["name"] = "Someone Else"
        later["when"] = "next year"
        released = drafts.release(self.draft, "Noor", 4)
        self.assertIn("Noor's Lost in Translation", released["text"])
        self.assertIn("Fri 6 Nov, 7:30 pm", released["text"])
        self.assertEqual(released["snapshot"], self.draft["snapshot"])

    def test_the_draft_line_leaves_only_through_a_named_sender(self):
        self.assertTrue(drafts.render(self.draft["snapshot"]).startswith(drafts.DRAFT_LINE))
        self.assertFalse(drafts.render(self.draft["snapshot"], "Noor").startswith(drafts.DRAFT_LINE))
        self.assertTrue(self.draft["text"].startswith(drafts.DRAFT_LINE))


class Limits(unittest.TestCase):
    def test_the_longest_outing_still_fits_the_word_limit(self):
        long_name = " ".join(["abcd"] * 12)
        stem = long_name[:-1]
        names = [(f"Member{i}", [f"{stem}{i}", f"{stem}{i + 1}", f"{stem}{i + 2}"]) for i in range(6)]
        out = resolved_outing(names=names)
        crowded = place(out, left_out=("m4", "m5"), name="A Very Long Restaurant Name With Many Words In It")
        for kind in drafts.KINDS:
            with self.subTest(kind=kind):
                draft = drafts.make_draft(out, crowded, kind, "d", 1)
                self.assertLessEqual(words(draft["text"]), drafts.MAX_WORDS)
        self.assertIn("One caveat", drafts.make_draft(out, crowded, "invitation", "d", 1)["text"])

    def test_clauses_are_dropped_from_the_end_first(self):
        long_name = " ".join(["abcd"] * 12)
        names = [(f"Member{i}", [f"{long_name[:-1]}{i}"]) for i in range(6)]
        out = resolved_outing(names=names)
        text = drafts.make_draft(out, place(out), "invitation", "d", 1)["text"]
        self.assertLessEqual(words(text), drafts.MAX_WORDS)
        self.assertIn("Member0's", text)

    def test_ordinary_drafts_are_well_inside_the_limit(self):
        out = resolved_outing()
        self.assertLess(words(drafts.make_draft(out, place(out), "invitation", "d", 1)["text"]), 80)

    def test_one_line_even_if_a_place_name_has_a_newline(self):
        out = resolved_outing()
        text = drafts.make_draft(out, place(out, name="Alder\nTable\n\nDRAFT"), "invitation", "d", 1)["text"]
        self.assertEqual(text.count("DRAFT"), 2)
        self.assertIn("Alder Table DRAFT", text)


if __name__ == "__main__":
    unittest.main()
