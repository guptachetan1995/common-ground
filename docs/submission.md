# Devpost submission copy — Common Ground

Field-by-field text for the Common Ground entry. The hackathon, "Agents, but with taste", is run by Qloo on
[Devpost](https://qloo.devpost.com/); entries close Fri 30 Oct 2026 at 11:45 pm EDT (Sat 31 Oct, 09:15 IST).

How to read this file:

- Each Devpost form field has its copy below, pasted as written. The sections after "Testing instructions" say where
  each rule and judging criterion is answered, and are not pasted.
- The Rules want the description to cover what the project does and how it works, and the overview adds that it
  should say what makes the project "Qloo-powered". "About the project" does both.
- A sentence about behaviour is backed by a test or by a step of the demo path.
- An HTML comment named hosted-url marks where the hosted demo's address goes once it is deployed, and one named
  video-url the optional video's YouTube link.
- Links are absolute because Devpost cannot follow relative ones.
- The hackathon wants a hosted demo, a public repository and a written description. It does not want a video.

## Project name

Common Ground: one bar per person, no averaged taste

## Elevator pitch

At most 200 characters. This one is 189:

> Four friends, four tastes, one table. An agent asks Qloo to rank the same places for each person, puts one bar per person on every pick and drafts the invite. Only people pick and sign off.

## About the project

**Try it:** open <!-- hosted-url -->, press **Try the sample group**, resolve each person's matches, choose
**Restaurant**, press **Compare places** and open a card. Then, under **Agent console**, press **Ask the agent to pick
a place**: the answer is `not_a_tool`, because picking is a person's verb and the agent has no tool for it.

**Why sample data.** This build went public before Qloo's API key came (it was requested on 17 October), so every
place, rank and affinity in the demo is invented. The banner reads "Synthetic sample data. Qloo is not being called."
and each card carries a "Sample data" stamp. The live path is written: `common_ground probe` checks Qloo's real
response shapes once a key exists, and the live source refuses every call until it has.

### Inspiration

Whenever a group plans one outing, the same argument breaks out: four people, four tastes, one table. The usual
endings are the loudest voice winning, a list averaged until nobody is delighted, or a vote that buries whose taste
lost. A fair answer needs a standing for each person on each candidate, so anyone left out can be seen, and it needs
the freedom to say "no place works for all of us" instead of faking one.

**Why not average, swipe or ask a language model.** Swipe-and-match apps find agreement only among places someone has
already listed, and each person has to judge every card. Group recommenders that blend everyone's signal return one
score per place, and a high group score can hide the one person a place fails. A language model names places from
memory: it holds no per-person ranking of any place, and it would call a guess agreement. Common Ground asks Qloo for
a separate ranking per person over one shared candidate list, orders the common places by the person each one serves
least (the least-misery strategy from group-recommender research, Masthoff 2004, applied to ranks), and treats "no
place is shared by everyone" as a real answer.

Qloo's taste graph is what makes a ranking per person possible, and it crosses domains, so someone's film or band can
be what finds them a place: "the thing that only works because it knows what people love".

An invitation or a booking request leaves in the organiser's name and cannot be recalled. Common Ground therefore
drafts and never sends, and the decisions that matter are ones no agent has a tool for.

### What it does

**It looks for the places where nobody in a group is left out, puts every person's standing on every pick, and drafts
the messages. People say which match they meant; the organiser alone picks a place and signs off a message.**

The organiser describes the outing: a label, the day, a price band, a city or neighbourhood, and each person with up to
three favourites, the names of public things only (a restaurant, a band, a film, a show, a book, a brand). Each name is
sent to Qloo to find a match.
1. **Say which match is meant.** One Qloo search per favourite returns candidates. The person it belongs to says which
   one they meant, from their own link, or the organiser says it for them and the page records that. Nothing is used
   until it is resolved, as Qloo's guidance advises. The organiser also picks the kind of place from tags Qloo returned.
2. **One search for the group.** Qloo's Insights API for places, anchored on everyone's resolved favourites, with the
   city, day, price level and kind applied inside Qloo. Up to 50 places come back, the long list.
3. **One ranking per person.** The same request for each person, with only that person's favourites as the signal and
   the long list's ids to rank, returns the places in that person's own order with Qloo's affinity.
4. **It stops when the answer is known.** A place is common when it is in the upper half of every person's own ranking.
   Once someone's ranking leaves none, the agent stops and reports how many rankings it did not spend.
5. **Standing, not a score.** Each card has a row and a bar per person, as long as that person ranks the place high,
   with a tick at that person's own upper half. "Why this place" holds Qloo's affinity on that person's own scale,
   Qloo's band, and the favourites that explain it. Nothing is averaged.
6. **"No place is shared by everyone" is an answer.** The page names who the closest places leave out and relaxes
   nothing: loosening a condition is the organiser's act.
7. **Pick, draft, sign off.** The organiser picks a place (ticking a box for each person it leaves out or has not
   ranked). The agent drafts an invitation and a booking request that read DRAFT until the organiser names themself as
   sender and signs off. A signed-off message is text to copy. The app sends, books and pays nothing.

Seven human decisions (resolving a match, adding a person's favourite, picking a place, signing off a message, changing
a condition, ruling out a place, lifting the call limit) are verbs that are never registered as tools: no agent can
call them, whether it is the page's own agent console or a model-driven agent over MCP. Each result also prints how
likely a common place is by chance for a group of that size.

### How we built it

The app contains no language model, by choice. Its agent is a rule-based comparison: each step applies a rule to a Qloo
response, and the README lists the rules. The tool registry is also exposed over the Model Context Protocol, as a
hosted Streamable HTTP endpoint (revision 2026-07-28, plus the two earlier ones that open with `initialize`) and as a
stdio relay to it, so any tool-calling model can operate it and none can commit. Both are tested with scripted MCP
clients.

Qloo is reached through three endpoints: `/search` (a favourite becomes an entity a person resolves), `/v2/tags` (a
valid tag for the kind of place) and `/v2/insights` for places, used twice over. Requests are built from a
per-endpoint list of allowed parameters, and the key travels only in the `X-Api-Key` header, from the server.

**A request traced end to end, ids elided.** For the sample group, one `GET /v2/insights` carries
`filter.type=urn:entity:place`, `signal.interests.entities` set to the eight favourites four people resolved,
`filter.exclude.entities` set to the same eight, `filter.location.query` set to the city, `filter.hours` set to the day,
`filter.price_level.min` and `.max`, `filter.tags` set to the kind tag, `feature.explainability=true` and `take=50`.
Then each person gets one call with `signal.interests.entities` set to that person's favourites alone,
`filter.results.entities` set to the 50 ids, and the same location, day, price and kind. The key rides in the
`X-Api-Key` header and every id is elided here. From each result the app reads the name, id, type, tags, position,
affinity and which of the person's favourites explain it; a card then shows each person's rank, bar, affinity and
Qloo's band. A person made the entity choice, since each match is resolved before use. The tag is one Qloo returned for
a word such as "restaurant", chosen by the organiser. No Qloo response is stored in the repository.

Fairness is a rule on Qloo's own order, not an average: a place is common when it is in the upper half of every
person's own ranking, with a tie tolerance at the line. Qloo's guide says scores are normalised per query and should be
read by position; it says this about brands, and extending it to people is our inference, which the README states.

Behind the page's buttons, the member page, the command line, the agent console and the MCP endpoint (and the relay,
through it) is a single function, `dispatch(tool, args, actor)`. The server needs only Python 3, so judges install
nothing. Claude Code wrote the code.

### What we measured, and on what

All of these were measured on the invented sample source, not on Qloo.

- **Calls.** The sample group (four people, two favourites each, 50 places) costs 14 calls: 8 searches, 1 tag search, 1
  group search and 4 rankings, of the 30 an outing may spend. The largest outing (six people, three favourites each)
  costs at most 26. In the test where the second ranking leaves nothing shared, the run stops at 6 calls and says one
  ranking was not spent.
- **What the page showed for the sample group.** 5 common places and 3 near ones, each near one naming who it leaves
  out, and the line "unrelated rankings would share about 3.1 of 50; this group shares 5".
- **Size and checks.** About 4,900 lines of Python with no third-party package, 2,200 lines of page files, and
  675 tests that run offline in about eight seconds, among them HTTP tests over a real socket, a test that fails if a
  Qloo-shaped id appears in the tree, and one that computes the contrast of every colour pair in light and dark.

### Challenges we ran into

- **Qloo's documentation says it ignores parameters it does not recognise, without an error.** Each endpoint has an
  allowlist, enforced when a request is built, so a typo cannot silently turn a condition off.
- **"No place comes close" cannot happen with complete rankings.** Some place always leaves out at most half the
  people, so it is common or near. The page says "no place comes close" only when Qloo ranked part of the long list.
- **Invented data must never stand in for a live answer.** After the daily ceiling a visitor should not meet a dead end,
  yet sample data must not pass for Qloo's. An outing keeps the source it opened on: one opened live stops with a named
  reason, and a new outing runs on sample data under its own banner and stamp.

### Accomplishments that we're proud of

- The gate is structure, not a promise: the seven human verbs are not in the registry, `dispatch` refuses them for the
  agent even when called directly, and the page, the agent console, the command line, the MCP endpoint and the stdio
  relay (through the endpoint) each end in the same function, with tests on each door.
- "No common ground" is a result with its own screen, and the effect of group size is printed beside every result.
- A card says whose every figure is, and where the organiser resolved a match on someone's behalf.
- The flow was walked by keyboard alone at 375 px, in light and dark, in one Chromium-based browser.

### What we learned

- Position in a person's own ranking is the safe thing to compare between people; applying Qloo's advice to people is
  the part we had to infer.
- Withholding a tool is stronger than asking an agent to hold back.
- The person gate depends on a label browsers add only to HTTPS pages, so the choice of host shaped the product.

### Known limits

- **No live calibration.** No Qloo key reached this build, so no response shape has met a real response.
- **No real client session.** The MCP endpoint and the relay are tested with scripted clients only.
- **One browser.** The walks used a Chromium-based browser; Firefox, Safari, a phone and a screen reader were not tried.

### What's next for Common Ground

- A day-trip mode using Qloo's destination type.
- A "not tonight" tag each person can set, which the organiser applies as an exclusion.
- Qloo's analysis endpoint, to show what two people's favourites have in common.

**Who would pay.** Venue, reservation and ticketing platforms: a group holding concert tickets still needs somewhere
to eat before the show, and a short list that shows each person's standing is a reason to book it where the tickets
were bought. Team dinners and offsites, where the organiser answers to everyone and must not leave anyone out. And any
assistant, over MCP: the hosted endpoint already serves the eight tools, so an assistant asked to plan a group evening
can call them and still cannot pick a place or sign a message off. One group costs at most 14 Qloo calls for four
people with two favourites each, and 26 for the largest outing (one search per favourite, one tag search, one group
search, one ranking per person).

## Built with

Tags to paste: python, html, css, javascript, model-context-protocol, qloo, render.

- Python 3 runs the server and the command line, with no packages
- The page is plain HTML, CSS and JavaScript
- The hosted agent endpoint and a stdio relay speak the Model Context Protocol
- Qloo supplies search, tags and insights
- Render serves the hosted demo on a free web service

If the demo is served from EC2 behind Caddy instead, swap the `render` tag for `amazon-ec2` and `caddy`.

## Try it out links

- Hosted demo: <!-- hosted-url -->
- Source: https://github.com/guptachetan1995/common-ground

## Video demo link

<!-- video-url -->

The optional video's YouTube link, uploaded as Public. The Rules do not ask for a video, so the field stays empty
without one.

## Gallery plan

Each gallery picture is a screenshot of the hosted app on its sample source. Every picture keeps the banner and the
"Sample data" stamp in frame and is captioned as sample data; nothing in the gallery is presented as a Qloo result.
Keys, cookies, agent addresses and member links are kept off screen, and Qloo's logo is not used.

1. **Thumbnail (3:2):** the picks, with a bar per person on each card.
2. **Saying which match is meant:** the agent's candidate for each favourite, and the resolve click.
3. **The agent's run:** the trace and call strip (each call's path, live, cache or sample, and milliseconds) with calls
   spent and calls not spent.
4. **A pick, opened:** each person's rank, affinity and band, and the favourites that explain it.
5. **No common ground:** who is left out of the closest places, and the conditions the organiser may change.
6. **Pick, draft, sign off:** an invitation reading DRAFT, then signed off with the sender named.
7. **The agent can't pick:** the agent console's refusal of `pick_place`.

## Answers to the hackathon-specific fields

The live form's own field list decides the final set; the answers are:

- Demo: <!-- hosted-url -->
- Repository: https://github.com/guptachetan1995/common-ground, public, with the MIT licence shown in About.
- Platform: web; any current browser on a phone or a desktop.
- Testing instructions: see the next section.
- Newness: this is a new project. Planning notes are dated 20 Oct, and every line of application code is written from
  20 Oct, within the Submission Period.

## Testing instructions

The Rules require access "free of charge and without any restriction". Common Ground is a web app, so:

1. **Nothing to sign in to, supply or install.** Open <!-- hosted-url --> in a current Chrome, Firefox or Safari. The
   banner at the top says which source you are looking at. This build runs its sample source, so the banner reads
   "Synthetic sample data. Qloo is not being called.", every figure is invented, and each card carries a "Sample data"
   stamp. The free host stops its program after 15 minutes without traffic. After a quiet spell the first load takes
   about a minute (Render shows its own loading page meanwhile) and the app comes back empty: earlier workspaces,
   personal links and agent addresses no longer exist, a tab left open says "This workspace is gone", and the first
   sample run repeats its calls, so it is slower than later ones. If the page is loaded over plain HTTP, or the browser
   sends no request label (older than 2023, or behind a proxy or privacy tool that strips it), a banner appears and
   resolving, picking and signing off are disabled, because the page tells you apart from an agent by that label; the
   agent console and an MCP client still work. Press **Try the sample group** and follow the README's path: resolve
   each person's matches, compare places, open a card, pick a place, draft and sign off both messages, then ask the
   agent console to pick a place: `not_a_tool`. In a text box, Enter presses the button beside it.

2. **What the demo spends.** On live data it makes Qloo calls from the server; on sample data it makes none. Each outing
   has a call limit (30 by default; the lift-limit button raises it to 60) and the server has a daily ceiling that
   protects the key. They are abuse guards, not a login or a paywall. The ceiling and the agent's allowance live in the
   server's memory, so each bounds one run of the server and is not a calendar day, and both restart with the host. When
   the ceiling is spent, an outing already running live stops with `daily_ceiling_spent` and is never switched; a new
   outing runs on sample data under the banner "Daily ceiling spent: showing synthetic sample data" with a stamp on every
   card. Favourites are the names of public things only, because each name is sent to Qloo.

3. **Locally, without a key:** clone the repository and run `python3 -m common_ground serve` (Python 3.11 or newer,
   nothing to install). It runs on synthetic data and says so.

4. **Locally, live:** put your own Qloo hackathon key in `QLOO_API_KEY` and run the same command. The key only works
   against the hackathon base URL, and the live source refuses to run until `common_ground probe` has checked Qloo's
   response shapes.

5. **Tests:** `python3 -m unittest discover -s tests -t . -q` runs 675 tests offline in about eight seconds.

6. **Bring your own agent (optional):** the page shows an agent address. An MCP client that speaks Streamable HTTP can
   use `<agent address>/mcp` (Claude Code: `claude mcp add --transport http common-ground <agent address>/mcp`); a
   stdio-only client can run `python3 -m common_ground mcp --address <agent address>` from a clone. The human verbs are
   missing from the tool list, and requesting one returns `not_a_tool`.

The demo stays up through at least 18 Nov 2026, two days after judging ends. If Qloo refuses a key, the page says so
instead of showing anything in its place.

## If a video is made: its YouTube details

For the optional video; the agent sends these with the file.

- **Visibility:** Public. The Rules say nothing about it, and Public rules out any access problem.
- **Category:** Science & Technology
- **Tags:** qloo, taste graph, ai agent, mcp, group planning, hackathon
- **Title:** Common Ground: one bar per person, no averaged taste (Qloo Agentic Hackathon)
- **Description:** the pitch above, then the demo and repository links, then a line saying it is an independent entry,
  not affiliated with or endorsed by Qloo, with a fictional group; it also names the Qloo endpoints used (search, tags,
  insights), and says whether the film shows sample data or live data.

## How each judging criterion is met

- **Technological Implementation.** Read the README's "What Qloo contributes" and "The fairness rule". On the demo
  page: the trace, the call strip, and the calls spent and saved. Behind it: the parameter allowlist, the limits, the
  allowance, the ceiling and the gate tests. Not shown: how the code fares against real Qloo responses, because no key
  reached this build.
- **Design.** One flow, from the outing to a signed-off message, in which every state can be reached: no key, an
  ambiguous favourite, nothing found, no common ground, a call limit reached, a spent ceiling, a Qloo error, a sleeping
  host. The page works at phone width, by keyboard, and passes a contrast test.
- **Potential Impact.** [What it does](#what-it-does), and who would pay for it
  ([What's next](#whats-next-for-common-ground)): reservation and ticketing platforms, team organisers, and any
  assistant over MCP, at no more than 14 Qloo calls for a group of four. The irreversible step, a message in the
  organiser's name, stays with the human.
- **Quality of the Idea.** A film or a band finds a place; each pick shows a standing per person instead of an average,
  and picks are ordered by the person served least (least misery), which neither a swipe app nor a blended group score
  shows; "no common ground" is a legitimate answer; only a human changes a condition; and the human gates follow Qloo's
  own guidance.

## Claims we decline to make

- **No language model inside the app.** The agent is a deterministic comparison; any model can drive the same tools over
  MCP.
- **No claim that a result is Qloo's while the banner says sample data.** The places, ranks and affinities of the sample
  source are invented, and the app has not yet been run against Qloo.
- **No prediction about any person.** Qloo's figures describe how its audiences relate to the things a person named.
  They are not a prediction about that person, and no card turns them into a rating of one.
- **No booking.** Nothing is reserved, confirmed or paid. A booking request stays a draft until the organiser signs it
  off, and the app never sends it.
- **No time, no price, no table.** Qloo's day filter is a day of the week, and its price level is a 1 to 4 band.
- **Only the long list is ranked.** The 50 places Qloo's group search returned are ranked; a place outside the long
  list is never checked. Ranks are relative, so a common place can still carry a Low band for someone, which is why
  the band sits beside the bar.
- **"Common" is not agreement.** It means the upper half of each person's own ranking of the long list, as Qloo orders
  it, under this app's rule.
- **A gate that holds against the agent's interfaces, not against everything.** A script that holds the workspace
  cookie and also sends a browser's `Sec-Fetch-Site: same-origin` header, a program that reads the browser's cookies,
  or an agent that drives the page by clicking its buttons acts as the person.
- **A person's own click only where it was theirs.** Otherwise the page says the organiser resolved the match for
  them, and an invitation never names a favourite the organiser resolved for someone.
- **No real group.** The outing and the people are fictional. What they love are real public things that Qloo resolves,
  shown only through what Qloo returns, with no endorsement.
- **No Qloo data in the repository.** Tests and the keyless mode use invented data.
- **No persistence.** The hosted demo keeps a workspace in memory only while its program runs, which on the free host
  ends after 15 minutes without traffic.

## Rule-by-rule answers

**Deliverables.** The agentic-tool requirement is met by three Qloo endpoints behind an MCP-connectable tool registry
and a comparison ([What it does](#what-it-does)). The demo is hosted and public with no login, so a judge can try it
end to end ([Try it out links](#try-it-out-links), [Testing instructions](#testing-instructions)); it shows sample data
and says so. The repository is public and the MIT licence sits at its root, where About shows it. The description is
[About the project](#about-the-project), and the case that Qloo is the differentiator is [Inspiration](#inspiration):
without Qloo there is no catalogue of places and no ranking per person.

**Conditions.** Access is free and unrestricted until judging ends; the limits are stated abuse guards
([Testing instructions](#testing-instructions)). Everything is in English. The project is new, not updated
([Answers to the hackathon-specific fields](#answers-to-the-hackathon-specific-fields)). No video is required, and one is
optional.

**Qloo's own submission guide** asks for a problem statement, the Qloo workflow and why, a redacted request to result,
a demo or screenshots without credentials, setup steps, and known limitations. They are in [Inspiration](#inspiration),
[How we built it](#how-we-built-it) (the request traced end to end), the gallery, [Testing
instructions](#testing-instructions) and [Claims we decline to make](#claims-we-decline-to-make), and [Known
limits](#known-limits) lists the known limitations.
