# Common Ground: demo film script

The optional demo film, at most 2:00. It was rendered on 30 Oct 2026 at 1:53.4 (113.40 s, 1920 × 1080, H.264 and
AAC, sha256 `d87915b7772ba775ef699295cc8b48eab365f259cc12cff89e27607452c46978`).

## What the film shows, and what it does not

- **Sample data only.** The page ran locally (`python3 -m common_ground serve` on loopback, with
  `COMMON_GROUND_PROVIDER=fake`), with no Qloo key in reach and no Qloo call made. Every place, rank and figure on
  screen is invented. The page's own banner, "Synthetic sample data. Qloo is not being called.", is in every frame of
  the app, and every card carries its "Sample data" stamp. The narration says so in its first line and never presents a
  result as Qloo's.
- **The real page, driven through its own controls.** One continuous session: the outing form typed in, Start the
  outing, Resolve per person, the kind of place, Compare places, Change the conditions, the agent console, Pick, Draft
  the invitation, the sender's name and Sign off. Nothing on screen is drawn by hand.
- **Framing only.** Each frame is a still of the page held for its sentence. The page is zoomed and scrolled, and its
  banner is pinned to the top of the frame so it stays readable; the banner's text is the page's own. A check stops
  the render if a member's personal link or the agent address (each carries a token) would be on screen.
- **The group is fictional.** Noor, Owen, Pia and Quinn, and their favourites, come from the repository's sample
  scenario, `scenarios/friday-table.json`.
- **Voice.** macOS text to speech. Each sentence is measured first and its frame is held for exactly that long plus a
  short pause, so no line is cut off.

## Beats

| # | Time | On screen | Narration |
|---|---|---|---|
| 1 | 0:00 | The outing form, filled in: The Friday Table (fictional), Fri 6 Nov, New York City, Friday, price levels 2 to 3, under the sample banner | Common Ground, running on invented sample data: no Qloo key is set, and the banner stays on screen to say so. |
| 1 | 0:08 | The people: Noor (the organiser) with Lost in Translation and Khruangbin, Owen with The Bear and Dune | Noor is planning a Friday dinner for four friends, and each names two favourites: a film, a band, a show, a book. |
| 2 | 0:17 | Candidates for "Lost in Translation", the movie first and selected, each marked "Synthetic sample data, not from Qloo" | The agent searches each favourite and lists candidates, the right kind of thing first. Only a person can say which one they meant. |
| 2 | 0:25 | Owen's favourites after Resolve: The Bear as a tv show, "Matched to The Bear (resolved by the organiser for Owen)", Dune as a book | Each friend confirms their own from a personal link, or Noor does it for them, and the page records who. |
| 3 | 0:32 | Compare places: "14 of 30 Qloo calls used", and the call strip: 8 searches, 1 tag search, 5 insights calls, all "sample", "0 live to Qloo" | One search for the group returns fifty places; then each friend's favourites rank that same list. Fourteen calls, all answered by the sample source, not Qloo. |
| 4 | 0:43 | Common places: Dunmore Larder and Rowan Canteen, each with a row and a bar per person ("Noor ranks it 18 of 50"), the halfway tick | Every pick gets one bar per person: that friend's own rank of the place, not a score. The tick marks the halfway line. Nothing is averaged. |
| 4 | 0:53 | "Why this place" opened on Dunmore Larder: each person's favourites with their explainability figures, and "Ordered by the rank of the person it serves least. That is this app's rule, not Qloo's." | Open a card, and every figure says whose it is. |
| 4 | 0:56 | Near places: Pemberton Kitchen and Dunmore Canteen, each "Leaves out Noor.", with "outside their upper half" | The near misses below name exactly who they leave out. |
| 5 | 1:00 | After Change the conditions (Los Angeles, price level 2) and Compare again: "No place is shared by everyone. The closest places below name who each one leaves out." 19 of 30 calls; "this group shares 0" of 23; Linden Cantina and Marlow Bistro each "Leaves out Owen." | Try the same four in Los Angeles at price level 2, and the answer is plain: no place is shared by everyone. The page names who each closest place leaves out, and loosens nothing. Only Noor changes a condition. |
| 6 | 1:15 | Agent console, "Ask the agent to pick a place": "Sent as the agent. not_a_tool: That is not something the agent can do." | The agent uses the same gateway as these buttons. Asked to pick a place, it gets: not a tool. Picking and signing off are never tools, here or over MCP. |
| 7 | 1:26 | Conditions set back to New York City, 2 to 3, compared again, Pick: "You picked Dunmore Larder.", Draft the invitation, Draft the booking request | Back in New York City, Noor picks a common place herself. Nothing is booked. |
| 7 | 1:31 | "Invitation to the group: Dunmore Larder" with the DRAFT stamp, "DRAFT. Not signed off. Do not send.", "Why this one: sample taste data, standing in for Qloo's, …", and the empty sender box | The agent drafts the invitation, marked DRAFT until Noor names herself as sender and signs it off. |
| 7 | 1:38 | "Signed off by Noor", the message text (still worded as sample data), Copy the message, Open in your mail app, Plain text | Signed off, it is text to copy. The app never sends, books or pays. |
| 8 | 1:44 | End card: the repository, `python3 -m common_ground serve`, the three steps to try, "This film shows invented sample data; Qloo was not called.", the independence line | To try it, clone the repository and run one command; no key needed. Press Try the sample group, then ask the agent to pick a place. |

The "no place is shared by everyone" result in beat 5 is a real run of the same outing on the sample source, reached
through Change the conditions. It was found by trying every city, day and price on the sample source and taking the
smallest change that gives it (no single change does); it was not staged. The candidates in beat 2 are the sample
source's: it lists the sample favourites' right kind first, and a person still confirms each one.

## YouTube details

- **Title:** Common Ground: an agent looking for the places no one in a group is left out of (Qloo Agentic Hackathon)
- **Visibility:** Public
- **Category:** Science & Technology
- **Tags:** qloo, taste graph, ai agent, mcp, group planning, hackathon
- **Description:** Four friends, four tastes. An agent built on Qloo's taste API ranks places per person, shows each
  one's standing and drafts the invite. Only people pick and sign. This film shows invented sample data: the app ran
  locally with no Qloo key, and Qloo was not called. In live mode the app uses Qloo's search, tags and insights
  endpoints. Source (MIT): https://github.com/guptachetan1995/common-ground. An independent entry in the Qloo Agentic
  Hackathon, not affiliated with or endorsed by Qloo; the group is fictional.
