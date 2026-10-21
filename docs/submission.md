# Devpost submission copy — Common Ground

Field-by-field text for the Common Ground entry. The hackathon, "Agents, but with taste", is run by Qloo on
[Devpost](https://qloo.devpost.com/); entries close Oct 30, 2026 at 11:45 pm EDT (Sat 31 Oct, 09:15 IST), and this one
is due two days early, on Wed 28 Oct.

**Status, 21 Oct 2026: the app is built and tested, it has never spoken to Qloo, and no hosted copy exists yet.** The
package holds the command line, the web page, a hosted-style MCP endpoint and a stdio relay to it, behind 674 offline
tests. No Qloo key had arrived when this was written, so every place and every figure in any demo today is invented
sample data, and the live source refuses to run until a first live check has compared Qloo's real response shapes
with the documented ones (the key-day probe). Files for two hosts are written and tested; the owner's hosting sitting is Sun 25 Oct, with
Tue 27 Oct as the retry. This file therefore separates what is true now from what becomes true only if something
happens, and marks the second kind **CONDITIONAL**.

How to read this file:

- Each Devpost form field has its copy below, followed by the rules those fields answer and a split of the work.
- A sentence about behaviour is backed by a test or by a step of the demo path. Where it is not backed yet, it says
  CONDITIONAL, and the table in the next section gives the wording that stands until then.
- A value that cannot exist yet (an address, a measured figure) says **pending** and names what will supply it.
- The form's real field list is read once the project exists, and this file is then brought into line.
- Links are absolute because Devpost cannot follow relative ones; an address that does not exist yet stays plain text.
- The hackathon wants a hosted demo, a public repository and a written description. It does not want a video.

## What is conditional

| Statement | Becomes true when | Wording that stands until then |
|---|---|---|
| The hosted demo makes live Qloo calls | The first live check (the probe) has passed, its block is in `common_ground/measured.py`, the repository is republished and the host is switched to `live` | "Today's demo runs on invented sample data; the banner on every page says so and each card carries a Sample data stamp." |
| Figures were calibrated on real responses (affinity range, ids a ranking accepts, which filters Qloo honours) | `docs/api-notes.md` holds the probe's measured values | "Live calibration has not been done." |
| A real MCP client session drives the hosted endpoint | A Claude session is recorded and its frames are checked for the address and token | "No real client session has been recorded; the endpoint and the relay are tested with scripted clients." |
| A video | It is made, at most 2:00, and uploaded as Public | No video. |
| The first sample run takes N seconds after a cold start | It is timed on the host | pending |
| A hosted address and a public repository link | The host exists; the repository is published | pending |

Elevator pitch for the live state, used only once the first row is true (194 characters): *Four friends, four tastes.
An agent asks Qloo where every place ranks for each person's own favourites, shows each person's standing as evidence
and drafts the invite. Only people pick and sign.*

## Project name

Common Ground

## Elevator pitch

At most 200 characters. This one is 193:

> Four friends, four tastes. An agent built on Qloo's taste API ranks places per person, shows each one's standing and drafts the invite. Today's demo uses sample data. Only people pick and sign.

## About the project

The Rules want the description to cover what the project does and how it works, and the overview adds that it should
say what makes the project "Qloo-powered".

**Quick path:** open the hosted demo (pending: its address is known after the 25 Oct sitting), press **Try the sample
group**, resolve each person's matches, press **Compare places**, and open a card. On sample data the banner reads
"Synthetic sample data. Qloo is not being called." and each card carries a "Sample data" stamp.

### Inspiration

Whenever a group plans one outing, the same argument breaks out: four people, four tastes, one table. The usual
endings are the loudest voice winning, a list averaged until nobody is delighted, or a vote that buries whose taste
lost. A fair answer needs a standing for each person on each candidate, so anyone left out can be seen, and it needs
the freedom to say "no place works for all of us" instead of faking one.

A language model could not do this from memory: it has no per-person ranking for any place, and it would call a guess
agreement. Qloo's taste graph does rank places for a person, and it crosses domains, so someone's film or band can be
what finds them a place: "the thing that only works because it knows what people love".

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
stdio relay to it, so any tool-calling model can operate it and none can commit. **CONDITIONAL:** a recorded Claude
(Anthropic) session in Claude Code will show this; none exists yet.

Qloo is reached through three endpoints: `/search` (a favourite becomes an entity a person resolves), `/v2/tags` (a
valid tag for the kind of place) and `/v2/insights` for places, used twice over. Requests are built from a
per-endpoint list of allowed parameters, and the key travels only in the `X-Api-Key` header, from the server. **Every
response shape the app reads is the documentation's and has not met a real response;** the live source refuses to run
until the probe has checked them.

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
through it) is a single function, `dispatch(tool, args, actor)`. The server needs only Python 3, so judges install nothing. In line with
the developer guide, the repository holds no Qloo response data; tests and keyless mode use made-up data that each page
labels as such. Claude Code wrote the code.

### What we measured, and on what

All of these were measured on the invented sample source, not on Qloo.

- **Calls.** The sample group (four people, two favourites each, 50 places) costs 14 calls: 8 searches, 1 tag search, 1
  group search and 4 rankings, of the 30 an outing may spend. The largest outing (six people, three favourites each)
  costs at most 26. In the test where the second ranking leaves nothing shared, the run stops at 6 calls and says one
  ranking was not spent.
- **What the page showed for the sample group.** 5 common places and 3 near ones, each near one naming who it leaves
  out, and the line "unrelated rankings would share about 3.1 of 50; this group shares 5".
- **Group size.** If rankings were unrelated, a place would sit in all the upper halves with probability one half to the
  power of the group's size: about 12.5 common places of 50 for two people, 6.3 for three, 3.1 for four, 1.6 for five
  and 0.8 for six. Real rankings are related, so the real count should be higher.
- **Size and checks.** About 4,900 lines of Python with no third-party package, 2,200 lines of page files, and
  674 tests that run offline in about eight seconds, among them HTTP tests over a real socket, a test that fails if a
  Qloo-shaped id appears in the tree, and one that computes the contrast of every colour pair in light and dark.
- **Cold start.** pending: timed on the host at the deploy walk (the free host stops after 15 minutes without traffic
  and the next visit waits about a minute).

### Challenges we ran into

- **Qloo's documentation says it ignores parameters it does not recognise, without an error.** Each endpoint has an
  allowlist, enforced when a request is built, so a typo cannot silently turn a condition off.
- **"No place comes close" cannot happen with complete rankings.** Some place always leaves out at most half the
  people, so it is common or near. The page says "no place comes close" only when Qloo ranked part of the long list.
- **The early stop needs a gap to fire on.** With smooth affinities, as the invented source has and Qloo's probably do,
  the tie tolerance makes two halves overlap, so a comparison can wait for the third ranking. The test uses a source
  whose affinities jump at the line, and the copy says "it stops when the answer is known", not "it stops early".
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
- No third-party package, and a tree that holds no Qloo data and no key, which a test and the verification script check.

### What we learned

- Position in a person's own ranking is the safe thing to compare between people; applying Qloo's advice to people is
  the part we had to infer.
- Withholding a tool is stronger than asking an agent to hold back.
- The person gate depends on a label browsers add only to HTTPS pages, so the choice of host shaped the product.
- Keeping every response-shape assumption in one module let the build go on without a key; nothing in it is calibrated
  until real responses have been read.

### What is not done yet

- **No live calibration.** The app has never called Qloo. The live source refuses to run until the first check passes.
- **No real client session.** The MCP endpoint and the relay are tested with scripted clients only.
- **The hosted demo runs on sample data until the first live check has passed,** and its cold-start time is unmeasured.
- **One browser.** The walks used a Chromium-based browser; Firefox, Safari, a phone and a screen reader were not tried.

### What's next for Common Ground

- A day-trip mode using Qloo's destination type.
- A "not tonight" tag each person can set, which the organiser applies as an exclusion.
- Qloo's analysis endpoint, to show what two people's favourites have in common.

## Built with

Tags to paste: python, html, css, javascript, model-context-protocol, qloo, render.

- Python 3 runs the server and the command line, with no packages
- The page is plain HTML, CSS and JavaScript
- The hosted agent endpoint and a stdio relay speak the Model Context Protocol
- Qloo supplies search, tags and insights
- Render hosts it for free (pending: amazon-ec2 and caddy instead, if the 25 Oct sitting picks EC2)

## Try it out links

- Hosted demo: its address (pending; it exists after the 25 Oct sitting, and it runs on sample data until the first
  live check has passed).
- Source: `github.com/guptachetan1995/common-ground` (pending; published before the sitting).

## Video demo link

None, unless the optional video gets made (pending; decided 27 Oct, and CONDITIONAL on the hosted demo being green by
then). The Rules do not ask for one.

## Gallery plan

Each gallery picture is a screenshot of the hosted app. While the app runs on sample data every picture keeps the banner
and the "Sample data" stamp in frame and is captioned as sample data; nothing in the gallery is presented as a Qloo
result unless it was taken on live data. Keys, cookies, agent addresses and member links are kept off screen, Qloo's logo
is not used, and wherever Qloo data appears it is on this page only, never in the repository.

1. **Thumbnail (3:2):** the picks, with a bar per person on each card.
2. **Saying which match is meant:** the agent's candidate for each favourite, and the resolve click.
3. **The agent's run:** the trace and call strip (each call's path, live, cache or sample, and milliseconds) with calls
   spent and calls not spent.
4. **A pick, opened:** each person's rank, affinity and band, and the favourites that explain it.
5. **No common ground:** who is left out of the closest places, and the conditions the organiser may change.
6. **Pick, draft, sign off:** an invitation reading DRAFT, then signed off with the sender named.
7. **The agent can't pick:** the agent console's refusal of `pick_place`.

## Answers to the hackathon-specific fields

The live form is checked later; the planned answers are:

- Demo: the hosted address (pending, after the 25 Oct sitting).
- Repository: `github.com/guptachetan1995/common-ground`, public, with the MIT licence shown in About (pending until
  it is published).
- Platform: web; any current browser on a phone or a desktop.
- Testing instructions: see the next section.
- Newness: this is a new project. Planning notes are dated 20 Oct, and every line of application code is written from
  20 Oct, within the Submission Period.

## Testing instructions

The Rules require access "free of charge and without any restriction". Common Ground is a web app, so:

1. **Nothing to sign in to, supply or install.** Open the demo address in a current Chrome, Firefox or Safari. The
   banner at the top says which source you are looking at: while the demo runs on sample data it reads "Synthetic
   sample data. Qloo is not being called.", every figure is invented, and each card carries a "Sample data" stamp. The
   free host stops its program after 15 minutes without traffic. After a quiet spell the first load takes about a minute
   (Render shows its own loading page meanwhile) and the app comes back empty: earlier workspaces, personal links and
   agent addresses no longer exist, a tab left open says "This workspace is gone", and the first sample run repeats its
   calls, so it is slower than later ones. If the page is loaded over plain HTTP, or the browser sends no request label
   (older than 2023, or behind a proxy or privacy tool that strips it), a banner appears and resolving, picking and
   signing off are disabled, because the page tells you apart from an agent by that label; the agent console and an MCP
   client still work. Press **Try the sample group** and follow the README's path: resolve each person's matches,
   compare places, open a card, pick a place, draft and sign off both messages, then ask the agent console to pick a
   place: `not_a_tool`. In a text box, Enter presses the button beside it.

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

5. **Tests:** `python3 -m unittest discover -s tests -t . -q`, offline.

6. **Bring your own agent (optional):** the page shows an agent address. An MCP client that speaks Streamable HTTP can
   use `<agent address>/mcp` (Claude Code: `claude mcp add --transport http common-ground <agent address>/mcp`); a
   stdio-only client can run `python3 -m common_ground mcp --address <agent address>` from a clone. The human verbs are
   missing from the tool list, and requesting one returns `not_a_tool`.

The demo is planned to stay up through at least 18 Nov 2026, which is two days after judging ends. If Qloo refuses the
key, the page says so instead of showing anything in its place.

## If a video is made: its YouTube details

Only if the optional video is made; the agent sends these with the file.

- **Visibility:** Public. The Rules say nothing about it, and Public rules out any access problem.
- **Category:** Science & Technology
- **Tags:** qloo, taste graph, ai agent, mcp, group planning, hackathon
- **Title:** Common Ground: an agent looking for the places no one in a group is left out of (Qloo Agentic Hackathon)
- **Description:** the pitch above, then the demo and repository links, then a line saying it is an independent entry,
  not affiliated with or endorsed by Qloo, with a fictional group; it also names the Qloo endpoints used (search, tags,
  insights), and says whether the film shows sample data or live data.

## How each judging criterion is met

- **Technological Implementation.** Read the README's "What Qloo contributes" and "The fairness rule". On the demo
  page: the trace, the call strip, and the calls spent and saved. Behind it: the parameter allowlist, the limits, the
  allowance, the ceiling and the gate tests. CONDITIONAL on live data: how the code fares against real responses is
  not yet known.
- **Design.** One flow, from the outing to a signed-off message, in which every state can be reached: no key, an
  ambiguous favourite, nothing found, no common ground, a call limit reached, a spent ceiling, a Qloo error, a sleeping
  host. The page works at phone width, by keyboard, and passes a contrast test.
- **Potential Impact.** [What it does](#what-it-does), run on live data once the first live check has passed. The
  irreversible step, a message in the organiser's name, stays with the human.
- **Quality of the Idea.** A film or a band finds a place; each pick shows a standing per person instead of an average;
  "no common ground" is a legitimate answer; only a human changes a condition; and the human gates follow Qloo's own
  guidance.

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
and a comparison ([What it does](#what-it-does)). The demo is to be hosted and public with no login, so a judge can try
it end to end ([Try it out links](#try-it-out-links), [Testing instructions](#testing-instructions)); until the first
live check has passed it shows sample data and says so. The repository is public and the MIT licence sits at its root,
where About will show it. The description is [About the project](#about-the-project), and the case that Qloo is the
differentiator is [Inspiration](#inspiration): without Qloo there is no catalogue of places and no ranking per person.

**Conditions.** Access is free and unrestricted until judging ends; the limits are stated abuse guards
([Testing instructions](#testing-instructions)). Everything is in English. The project is new, not updated
([Answers to the hackathon-specific fields](#answers-to-the-hackathon-specific-fields)). No video is required, and one is
optional.

**Qloo's own submission guide** asks for a problem statement, the Qloo workflow and why, a redacted request to result,
a demo or screenshots without credentials, setup steps, and known limitations. They are in [Inspiration](#inspiration),
[How we built it](#how-we-built-it) (the request traced end to end), the gallery, [Testing
instructions](#testing-instructions) and [Claims we decline to make](#claims-we-decline-to-make), and [What is not done
yet](#what-is-not-done-yet) lists the known limitations.

## Division of labour before submitting

Before the Submit click, the agent does everything except the owner's three acts, working in the owner's logged-in
Chrome. It builds, tests and publishes the app and its repository, then walks the live address logged out. It reads the
live form and updates this file to fit, creates the project from the owner's registration and fills every field
(gallery, thumbnail, tags and links included) while leaving the agreement boxes alone, and turns the placeholders above
into real addresses. It then runs the judge-panel review, acts on it, and checks each rule against the draft, the demo
and the repository.

The owner's three acts:
1. Click **Create Web Service** for this entry's service in the existing Render workspace during the Sunday 25 Oct
   hosting sitting, pasting the API key as the service's secret only if the first live check has passed (otherwise the
   service starts on sample data and the key is pasted later), or click the EC2 launch if that sitting picks EC2. A
   failed click gets one retry on Tue 27 Oct.
2. Upload the video to YouTube as **Public** and paste the link, only if a video is made (27 Oct).
3. Tick the agreement boxes and click **Submit** (28 Oct).
