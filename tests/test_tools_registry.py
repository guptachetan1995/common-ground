import json
import unittest

from common_ground import agent_tools, fair_share, outings, person_verbs


class EveryToolIsDescribedForSomeoneWhoCannotSeeTheScreen(unittest.TestCase):
    def test_each_description_says_what_the_tool_does_not_do(self):
        for tool in agent_tools.TOOLS.values():
            with self.subTest(tool.name):
                self.assertRegex(tool.description, r"\b[Dd]oes not\b|\bnever\b|\bNever\b")
                self.assertGreater(len(tool.description.split()), 25)

    def test_no_description_points_at_the_page(self):
        for tool in agent_tools.TOOLS.values():
            with self.subTest(tool.name):
                self.assertNotRegex(tool.description, r"(?i)\b(click|button|screen|page)\b")

    def test_a_tool_that_spends_says_so_and_one_that_does_not_say_it_does_not_call_qloo(self):
        spends = {"look_up_favourite", "look_up_kind"}
        for name in spends:
            self.assertIn("Spends one call", agent_tools.TOOLS[name].description)
        for name in ("show_evidence", "read_outing", "spend_report"):
            self.assertIn("call Qloo", agent_tools.TOOLS[name].description)
        self.assertIn("call limit", agent_tools.TOOLS["run_comparison"].description)

    def test_the_drafting_tool_says_a_person_signs_off_and_the_comparison_says_it_picks_nothing(self):
        drafting = agent_tools.TOOLS["write_draft"].description
        self.assertIn("only the organiser can sign a message off", drafting)
        self.assertIn("pick a place", agent_tools.TOOLS["run_comparison"].description)
        self.assertIn("only a person can", agent_tools.TOOLS["open_outing"].description)

    def test_the_privacy_hints_are_in_the_description_of_the_tool_that_takes_the_names(self):
        text = agent_tools.TOOLS["open_outing"].description
        for phrase in ("public things only", "never a person", "never an address", "never sent to Qloo"):
            self.assertIn(phrase, text)


class EverySchemaIsPlainJsonSchema(unittest.TestCase):
    def test_a_closed_object_with_every_required_key_declared(self):
        for tool in agent_tools.TOOLS.values():
            schema = tool.args.schema
            with self.subTest(tool.name):
                self.assertEqual((schema["type"], schema["additionalProperties"]), ("object", False))
                self.assertLessEqual(set(schema["required"]), set(schema["properties"]))
                json.dumps(schema)
        for name, verb in person_verbs.VERBS.items():
            with self.subTest(name):
                self.assertLessEqual(set(verb.args.required), set(verb.args.declared))

    def test_listing_is_name_description_and_input_schema_and_nothing_else(self):
        listing = agent_tools.listing()
        self.assertEqual([t["name"] for t in listing], list(agent_tools.TOOLS))
        for entry in listing:
            self.assertEqual(sorted(entry), ["description", "inputSchema", "name"])

    def test_open_outing_declares_exactly_the_arguments_of_the_plan(self):
        declared = agent_tools.TOOLS["open_outing"].args.declared
        self.assertEqual(sorted(declared), sorted((
            "label", "members", "place_text", "day", "price_min", "price_max", "radius_m", "kind_query",
            "when",
        )))
        required = agent_tools.TOOLS["open_outing"].args.required
        self.assertEqual(required, ("label", "members", "place_text", "day"))

    def test_the_limits_in_the_descriptions_are_the_limits_in_the_code(self):
        tool = agent_tools.TOOLS["open_outing"]
        self.assertIn(f"2 to {fair_share.MAX_MEMBERS} members", tool.description)
        self.assertIn("up to three favourites", tool.description)
        self.assertEqual(fair_share.MAX_FAVOURITES, 3)
        for name, limit in (("label", outings.MAX_LABEL), ("place_text", outings.MAX_PLACE_TEXT),
                            ("when", outings.MAX_WHEN)):
            self.assertIn(str(limit), tool.args.declared[name]["description"])


if __name__ == "__main__":
    unittest.main()
