#!/usr/bin/env bash
# Checks for the Common Ground entry.
# Before the Python code lands, it checks the documents that a judge's clone and the planning
# tree both carry. In the planning tree it also compares this entry's wording and names with the
# sibling entry's. Once the Python package exists, it also compiles it and runs the tests. The
# entry has no third-party dependency, so there is nothing to install first.
# Written for the bash 3.2 that ships with macOS: no mapfile, no associative arrays, no
# negative array indices, and no expansion of an empty array.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

fail() {
  echo "verify: FAIL: $1" >&2
  exit 1
}
ok() { echo "  ok: $1"; }
section() { echo "== $1"; }

# The plan (SPEC.md) is never published, so the checks that read it run only in the planning
# tree, recognised by the publishing and verification scripts two levels up.
in_monorepo=false
if [ -f ../../bin/publish.sh ] && [ -f ../../bin/verify.sh ]; then in_monorepo=true; fi

# Prints the body of one "## <title>" section of a Markdown file, without the blank lines
# around it: exactly what gets pasted into a form field.
section_body() {
  awk -v want="## $2" '
    $0 == want { on = 1; next }
    on && /^## / { on = 0 }
    on { lines[++n] = $0 }
    END {
      first = 1
      while (first <= n && lines[first] ~ /^[[:space:]]*$/) first++
      last = n
      while (last >= first && lines[last] ~ /^[[:space:]]*$/) last--
      for (i = first; i <= last; i++) print lines[i]
    }' "$1"
}

char_count() { printf '%s' "$1" | LC_ALL=en_US.UTF-8 wc -m | tr -d ' '; }

# True when a phrase appears in a file even if the Markdown wraps it across lines.
has_phrase() { tr '\n' ' ' < "$1" | tr -s ' ' | grep -qF -- "$2"; }

section "entry root files"
for f in README.md LICENSE .gitignore .env.example docs/submission.md; do
  [ -f "$f" ] || fail "$f is missing"
  ok "$f"
done
[ -x verify.sh ] || fail "verify.sh is not executable"
ok "verify.sh is executable"

section "the deploy files"
for f in docs/deploy.md deploy/ec2/user-data.sh; do
  [ -f "$f" ] || fail "$f is missing"
  ok "$f"
done
bash -n deploy/ec2/user-data.sh || fail "deploy/ec2/user-data.sh does not parse"
[ "$(wc -c < deploy/ec2/user-data.sh)" -lt 16384 ] ||
  fail "deploy/ec2/user-data.sh is over the 16 KB limit AWS puts on user data"
grep -qE '^QLOO_API_KEY=[[:space:]]+# <<< the one line to edit' deploy/ec2/user-data.sh ||
  fail "the boot script's key line must be empty and carry its marker"
has_phrase docs/deploy.md 'Until the probe has run, deploy with `fake`' ||
  fail "docs/deploy.md lost the rule that the hosted copy serves the sample source until the probe has run"
has_phrase docs/deploy.md 'If a card, phone or ID screen appears at any step' ||
  fail "docs/deploy.md lost the instruction to stop at a card, phone or ID screen"
for blueprint in render.yaml render.yml; do
  if [ -e "$blueprint" ]; then
    grep -qE '^[[:space:]]*plan:[[:space:]]*free[[:space:]]*$' "$blueprint" ||
      fail "$blueprint does not name the free plan (Render's default plan is paid)"
  fi
done
ok "both files present, the boot script parses and fits user data, its key line is empty, the guide keeps its two rules"

section "the licence is MIT and names the copyright holder"
[ "$(sed -n 1p LICENSE)" = "MIT License" ] || fail "LICENSE does not start with the MIT License title"
grep -qx 'Copyright (c) 2026 Chetan Gupta' LICENSE || fail "LICENSE lost its copyright line"
ok "MIT, Copyright (c) 2026 Chetan Gupta"

section "the key stays out of the repository"
# The published copy is a fresh git repository in which only this directory's .gitignore
# applies, so it alone keeps a local .env and the private cache out.
grep -qx '\.env' .gitignore || fail ".gitignore does not ignore .env"
grep -qx '\.cache/' .gitignore || fail ".gitignore does not ignore .cache/ (the private cache and ledger)"
grep -qx 'QLOO_API_KEY=' .env.example || fail ".env.example must carry an empty QLOO_API_KEY="
for setting in COMMON_GROUND_PORT PORT COMMON_GROUND_BIND COMMON_GROUND_ALLOWED_HOSTS COMMON_GROUND_TRUST_PROXY COMMON_GROUND_CALL_LIMIT; do
  grep -qx "$setting=" .env.example || fail ".env.example must carry an empty $setting="
done
if grep -nE '^[A-Za-z_]+=.+' .env.example; then fail ".env.example carries a value; every setting must stay empty"; fi
if grep -rnIE 'QLOO_API_KEY=[A-Za-z0-9_-]{8,}' . \
  --exclude-dir=.git --exclude-dir=.cache --exclude-dir=out --exclude='.env' --exclude='.env.*' \
  --exclude='verify.sh'; then
  fail "a QLOO_API_KEY with a value is in the tree"
fi
if grep -rnIiE 'x-api-key"?[:=] *["'"'"']?[A-Za-z0-9_-]{20,}' . \
  --exclude-dir=.git --exclude-dir=.cache --exclude-dir=out --exclude='.env' --exclude='.env.*' \
  --exclude='verify.sh'; then
  fail "an X-Api-Key header with a key-shaped value is in the tree"
fi
ok ".env and .cache/ ignored, every example setting empty, no key-shaped value in the tree"

section "no Qloo response data in the public repository"
# Qloo's developer guide: "Do not store Qloo response data in a public repository". Real entity
# ids are UUIDs, so any UUID outside the reserved synthetic range fails.
real_ids="$(grep -rIiEho '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' . \
  --exclude-dir=.git --exclude-dir=.cache --exclude-dir=out --exclude='.env' --exclude='.env.*' \
  --exclude='verify.sh' | grep -viE '^00000000-0000-4000-8000-' || true)"
[ -z "$real_ids" ] || fail "a UUID outside the synthetic range 00000000-0000-4000-8000-… is in the tree: $real_ids"
ok "every id in the tree is in the synthetic range"

section "the published documents stand on their own"
published=(README.md .env.example)
for f in docs/*.md; do published+=("$f"); done
if grep -nwE 'SPEC(\.md)?' "${published[@]}"; then
  fail "a published file mentions the plan file, which is never published"
fi
private_name="hackathons"'-2026'
private_paths='(^|[^A-Za-z0-9_./-])(\.\./)*(entries/[a-z0-9-]+|bin/(publish|pages|ready|verify)\.sh|bin/video/)'
if grep -nE "$private_paths|$private_name" "${published[@]}"; then
  fail "a published file points into the private planning tree"
fi
ok "no plan-file or private-tree references in ${published[*]}"

section "no text carried over from the sibling entry"
# Each name below belongs to the other entry for this hackathon. Its verbs may be named in the
# plan's distinctness table, and nowhere else.
sibling='OPEN_SLOT_|open_slot|X-Open-Slot|Open Slot|programme|assign_slot|approve_inquiry|find_anchor|plan_acts|draft_inquiry|suggest_slots'
if grep -nE "$sibling" "${published[@]}"; then
  fail "a published file carries a name from the sibling entry"
fi
if [ "$in_monorepo" = true ] && grep -nE 'OPEN_SLOT_|open_slot|X-Open-Slot|assign_slot|approve_inquiry|find_anchor|plan_acts|draft_inquiry|suggest_slots' SPEC.md |
  grep -vE 'distinctness|`confirm_anchor`, `assign_slot`, `approve_inquiry`'; then
  fail "SPEC.md carries a name from the sibling entry outside the distinctness table"
fi
ok "none of the sibling entry's names outside the plan's distinctness table"

section "no unresolved placeholders"
placeholder_files=("${published[@]}")
if [ "$in_monorepo" = true ]; then placeholder_files+=(SPEC.md); fi
if grep -nE '(^|[^A-Za-z])(TODO|TBD)([^A-Za-z]|$)|\[owner\]|[Oo]wner fills in|<placeholder>|PLACEHOLDER' \
  "${placeholder_files[@]}"; then
  fail "a placeholder is left in: ${placeholder_files[*]}"
fi
ok "none in ${placeholder_files[*]}"

section "the README states what a judge needs"
grep -q 'never registered as a tool' README.md ||
  fail "README.md no longer says the human verbs are never registered as a tool"
grep -q '^## Data that leaves your machine' README.md ||
  fail "README.md lost its exact statement of what is sent to Qloo"
grep -q 'not affiliated with or endorsed by Qloo' README.md ||
  fail "README.md lost the independence line"
grep -q 'No Qloo response is stored in this repository' README.md ||
  fail "README.md lost the statement that no Qloo response is stored here"
for verb in resolve_match add_own_favourite pick_place sign_off_message change_conditions rule_out_place lift_call_limit; do
  grep -q "\`$verb\`" README.md || fail "README.md does not name the human verb $verb"
done
has_phrase README.md 'Sec-Fetch-Site' ||
  fail "README.md lost the statement of what the cookie gate does and does not hold against"
has_phrase README.md 'does **not** hold against' ||
  fail "README.md no longer says where the human gate does not hold"
has_phrase README.md 'names of public things only' ||
  fail "README.md lost the line telling visitors to type public things only"
has_phrase docs/submission.md 'names of public things only' ||
  fail "docs/submission.md lost the line telling visitors to type public things only"
has_phrase README.md 'only on HTTPS pages' ||
  fail "README.md lost the statement that the person label exists only on HTTPS pages"
has_phrase README.md 'A request traced end to end, ids elided' ||
  fail "README.md lost its redacted request-to-result section"
has_phrase docs/submission.md 'A request traced end to end, ids elided' ||
  fail "docs/submission.md lost its redacted request-to-result paragraph"
has_phrase README.md 'not a prediction about that person' ||
  fail "README.md lost the sentence that Qloo's figures are not a prediction about that person"
has_phrase docs/submission.md 'not a prediction about that person' ||
  fail "docs/submission.md lost the sentence that Qloo's figures are not a prediction about that person"
has_phrase README.md 'this entry'"'"'s inference' ||
  fail "README.md lost the statement that applying Qloo's per-query advice to people is this entry's inference"
has_phrase docs/submission.md 'sends no request label' ||
  fail "docs/submission.md testing instructions lost the sentence about a browser that sends no request label"
has_phrase README.md 'not a calendar day' ||
  fail "README.md no longer says the call ceiling and allowance live in memory"
has_phrase docs/submission.md 'not a calendar day' ||
  fail "docs/submission.md testing instructions no longer say the ceiling lives in memory"
has_phrase README.md 'upper half of every person' ||
  fail "README.md lost the definition of a common place"
has_phrase README.md 'outside the long list is never checked' ||
  fail "README.md lost the limit that only the long list is ranked"
has_phrase docs/submission.md 'outside the long list is never checked' ||
  fail "docs/submission.md lost the limit that only the long list is ranked"
has_phrase README.md 'unrelated' ||
  fail "README.md lost the effect-of-group-size statement"
has_phrase README.md 'resolved by the organiser for' ||
  fail "README.md lost the label shown where the organiser resolved a match for someone"
has_phrase README.md 'python3 -m common_ground serve' ||
  fail "README.md lost the serve command"
has_phrase README.md 'python3 -m unittest discover -s tests -t . -q' ||
  fail "README.md lost the test command"
has_phrase README.md './verify.sh' ||
  fail "README.md lost the verify command"
has_phrase README.md '15 minutes without traffic' ||
  fail "README.md lost the statement that the free host stops after 15 idle minutes"
has_phrase docs/submission.md '15 minutes without traffic' ||
  fail "docs/submission.md lost the statement that the free host stops after 15 idle minutes"
if [ -f common_ground/__main__.py ]; then
  if grep -q 'Status: planned, not yet built' README.md; then
    fail "common_ground/__main__.py exists, but README.md still says the entry is planned, not yet built"
  fi
else
  grep -q 'Status: planned, not yet built' README.md ||
    fail "there is no code yet, so README.md must say it is planned, not yet built"
fi
ok "gate, privacy, independence, no-Qloo-data, fairness, cold-start and status lines present; the seven verbs are named"

section "no false idle-timeout or workspace-timeout claim"
# Render's free web services stop after 15 minutes without traffic (free-tier page, read 20 Oct 2026)
# and memory goes with the process, so no published file may promise a longer life.
if grep -nIiE 'hours of inactivity|idle timeout|7200|WORKSPACE_TTL|two hours of|2 hours of' \
  README.md .env.example docs/*.md; then
  fail "a published file makes a workspace-lifetime claim the free host cannot keep"
fi
ok "none in README.md, .env.example, docs/*.md"

section "no price, availability, booking or liking claim in the published copy"
claim_files=(README.md)
for f in docs/*.md; do claim_files+=("$f"); done
if grep -niE 'costs less|sells better|affordable|cheaper|more available|price has moved|open now|a table is available|has a table|guaranteed|perfect for (the|your) (whole )?group|everyone agrees' \
  "${claim_files[@]}"; then
  fail "a published file makes a price, availability, booking or agreement claim the honesty rules forbid"
fi
# "will like" and "will love" are allowed only where they are disclaimed.
if grep -niE 'will (like|love|enjoy)' "${claim_files[@]}" | grep -viE 'whether|never|not |no |nothing|anyone'; then
  fail "a published file says a person will like a place"
fi
ok "none of: open now, a table is available, guaranteed, everyone agrees, and the price claims; no undisclaimed 'will like'"

section "the submission copy fits the form"
name="$(section_body docs/submission.md "Project name")"
[ -n "$name" ] || fail "docs/submission.md has no '## Project name' section"
n="$(char_count "$name")"
[ "$n" -le 60 ] || fail "the project name is $n characters; Devpost's standard limit is 60"
ok "Project name: $n of 60"
pitch="$(awk '/^## Elevator pitch/{f=1;next} /^## /{f=0} f && /^> /{sub(/^> /,""); print; exit}' docs/submission.md)"
[ -n "$pitch" ] || fail "docs/submission.md has no quoted elevator pitch"
pitch_len="$(char_count "$pitch")"
[ "$pitch_len" -le 200 ] || fail "the elevator pitch is $pitch_len characters; Devpost allows 200"
section_body docs/submission.md "Elevator pitch" | grep -q "This one is $pitch_len:" ||
  fail "docs/submission.md must state the pitch length as 'This one is $pitch_len:'"
ok "Elevator pitch: $pitch_len of 200, and its stated length is current"
about="$(section_body docs/submission.md "About the project")"
[ -n "$about" ] || fail "docs/submission.md has no '## About the project' section"
n="$(char_count "$about")"
# Devpost states no limit for the story; 12,000 is this entry's own ceiling.
[ "$n" -le 12000 ] || fail "'About the project' is $n characters; this entry keeps it under 12000"
ok "About the project: $n of 12000 (this entry's own ceiling)"
for title in "Built with" "Try it out links" "Video demo link" "Testing instructions"; do
  [ -n "$(section_body docs/submission.md "$title")" ] || fail "docs/submission.md has no '## $title' section"
  ok "$title"
done
if grep -nE '\]\((\.\.?/|[A-Za-z0-9_./-]+\.md)' docs/submission.md; then
  fail "docs/submission.md links a relative path; the form can't follow it"
fi
ok "no relative links"

if [ "$in_monorepo" = true ]; then
  section "SPEC.md sections, in the fixed order"
  [ -f SPEC.md ] || fail "SPEC.md is missing"
  expected=(
    "1. Concept"
    "2. User and problem"
    "3. Why this wins"
    "4. What the agent does, what only a human does"
    "5. Tool list"
    "6. Qloo API contract"
    "7. Architecture and stack pin"
    "8. Data model"
    "9. Demo script"
    "10. Build plan"
    "11. Owner steps"
    "12. Risks"
    "13. Submission checklist"
  )
  found=()
  while IFS= read -r line; do found+=("$line"); done < <(grep -E '^## ' SPEC.md)
  [ "${#found[@]}" -eq "${#expected[@]}" ] ||
    fail "SPEC.md has ${#found[@]} top-level sections, expected ${#expected[@]}"
  i=0
  while [ "$i" -lt "${#expected[@]}" ]; do
    case "${found[$i]}" in
      "## ${expected[$i]}"*) ok "${expected[$i]}" ;;
      *) fail "section $((i + 1)) is '${found[$i]}', expected '## ${expected[$i]}…'" ;;
    esac
    i=$((i + 1))
  done
  [ "${found[$((${#found[@]} - 1))]}" = "## 13. Submission checklist" ] ||
    fail "SPEC.md does not end with the submission checklist"
  ok "the submission checklist is the last section"

  section "the submission-count clause is quoted verbatim, with its caps (read 20 Oct 2026)"
  for clause in \
    "An Entrant may submit more than one Submission, however, each Submission must be unique and substantially different from each of the Entrant’s other Submissions, as determined by the Sponsor and Devpost in their sole discretion." \
    "Each Project is eligible to win one (1) prize." \
    "Verdict: multiple entries are allowed, with no numeric cap in the Rules." \
    "What changed in the Rules since the 7 Oct read:"; do
    grep -qF -- "$clause" SPEC.md || fail "SPEC.md does not carry: $clause"
    ok "${clause:0:72}"
  done

  section "the concept is scored and its distinctness from the sibling entry is tested"
  for part in "### Scored, and how it differs from \`open-slot\`" "**Distinctness test.**" \
    "| The user |" "| The job |" "| What Qloo is asked |" "| The human verbs |"; do
    grep -qF -- "$part" SPEC.md || fail "SPEC.md section 1 does not carry: $part"
    ok "$part"
  done

  section "every judging criterion is quoted verbatim (Rules §6, read 20 Oct 2026)"
  for criterion in \
    "**Technological Implementation:** How thoroughly and skillfully does the project use Qloo? Does the code reflect genuine effort and a working, non-trivial implementation?" \
    "**Design:** Does the project deliver a complete, coherent product experience, not just a technical proof of concept?" \
    "**Potential Impact:** Does the project make a credible, specific case for solving a real problem for a real audience and does the solution actually address that problem based on what's demonstrated?" \
    "**Quality of the Idea:** Is this a creative, non-obvious use of Qloo and does the team demonstrate genuine understanding of the problem space they're working in?" \
    "The first stage will determine via pass/fail whether the ideas meet a baseline level of viability, in that the Project reasonably fits the theme and reasonably applies the required APIs/SDKs featured in the Hackathon."; do
    grep -qF -- "$criterion" SPEC.md || fail "section 3 does not quote: $criterion"
    ok "${criterion:0:64}"
  done

  section "the checklist carries the rules' own words (read 20 Oct 2026)"
  checklist="$(awk '/^## 13\. Submission checklist/ { on = 1 } on' SPEC.md)"
  for item in \
    "Registration and Submission Period: September 30, 2026 (9:00 am Eastern Time) – October 30, 2026 (11:45 pm Eastern Time)" \
    "Judging Period: November 2, 2026 (12:00 pm Eastern Time) – November 16, 2026 (11:45 pm Eastern Time)" \
    "Register for the Hackathon on the Hackathon Website by clicking the “Join Hackathon” button." \
    "Entrants will be given access to the Qloo API by filling out the Google Form here:" \
    "Functionality: The Project must be capable of being successfully installed and running consistently on the platform for which it is intended and must function as depicted in the video and/or expressed in the text description." \
    "Provide a link to a functional demo application" \
    "The repository must be public and open source by including an open source license file." \
    "Include a text description that should explain the features and functionality of your Project." \
    "The Entrant must make the Project available free of charge and without any restriction, for testing, evaluation and use by the Sponsor, Administrator and Judges until the Judging Period ends." \
    "Once the Submission Period has ended, you may not make any changes or alterations to your Submission" \
    "A live, working app participants can try end-to-end." \
    "Submissions that only run locally or rely on private access will not qualify." \
    "An open-source license, with the file visible in About section of your repo." \
    "NOTE: Demo videos are not required." \
    "FINAL CHECK"; do
    printf '%s\n' "$checklist" | grep -qF -- "$item" || fail "the checklist does not carry: $item"
    ok "${item:0:72}"
  done

  section "the deadline, the host rule, the key hygiene and the demo's honesty are pinned"
  has_phrase SPEC.md 'Sat 31 Oct 2026, 09:15 IST' || fail "SPEC.md no longer pins the deadline in IST"
  has_phrase SPEC.md 'https://hackathon.api.qloo.com' || fail "SPEC.md no longer pins the hackathon base URL"
  has_phrase SPEC.md 'X-Api-Key' || fail "SPEC.md no longer pins the key header"
  has_phrase SPEC.md 'Do not store Qloo response data in a public repository' ||
    fail "SPEC.md no longer quotes the developer guide's storage rule"
  has_phrase SPEC.md '**Storage: no Qloo data in the public repository.**' ||
    fail "SPEC.md no longer pins the no-Qloo-data design"
  has_phrase SPEC.md 'hard ceiling is 120 s' || fail "SPEC.md no longer pins the 120 s video ceiling"
  has_phrase SPEC.md 'bin/video/out/common-ground/final-narrated.mp4' ||
    fail "SPEC.md no longer pins where the finished video lives"
  for verb in resolve_match add_own_favourite pick_place sign_off_message change_conditions rule_out_place lift_call_limit; do
    has_phrase SPEC.md "\`$verb\`" || fail "SPEC.md does not name the human verb $verb"
  done
  has_phrase SPEC.md '`COMMON_GROUND_CALL_LIMIT`, default 30' || fail "SPEC.md no longer pins the call limit of 30"
  has_phrase SPEC.md 'At most 14 live calls' || fail "SPEC.md no longer pins the probe's 14-call limit"
  has_phrase SPEC.md '**No Qloo API call was made: there is no key.**' ||
    fail "SPEC.md no longer says that no Qloo call was made in S0"
  ok "deadline; base URL; header; storage rule; 120 s ceiling; video path; seven verbs; call limit; probe limit"

  section "the plan's decisions stay pinned (S0, 20 Oct 2026, revised after review)"
  for pin in \
    '`LONG_LIST`' \
    '`HALF`' \
    '`TIE_EPSILON`' \
    '`filter.results.entities`' \
    '`query.affinity`' \
    '**UNVERIFIED**' \
    'normalized per query' \
    "this plan's inference, not a statement of Qloo's" \
    'There is no composite score and nothing is averaged' \
    'only way a condition changes after the outing opens' \
    '`resolvedBy`' \
    '`organiser_for`' \
    'test_resolutions_scoped.py' \
    'The person gate needs HTTPS' \
    '`no_fetch_metadata`' \
    '`limiterKey`' \
    'Render grants 750 Free instance hours to each workspace per calendar month' \
    'goes 15 minutes without receiving any inbound traffic' \
    'P5, the personal ranking, exactly as the comparison will make it' \
    'T3, the personal ranking' \
    'There is no fallback mode' \
    'fails T3, and the entry stops the same day' \
    'is the **first** act' \
    '`shapes_unverified`' \
    '`measured.UNVERIFIED`' \
    'D0, Fri 23 Oct 12:00 IST' \
    'Mon 26 Oct 18:00 IST' \
    'A retry day: Tue 27 Oct' \
    'about 26' \
    '24 to 28' \
    '2026-07-28' \
    '2025-11-25' \
    '2025-06-18' \
    'the hosted Streamable-HTTP MCP endpoint' \
    'a second free Render web service' \
    'in that same sitting' \
    'This entry needs no join, no key request and no new account' \
    'redacted request-to-result explanation, including any entity/tag choices' \
    'other high-impact decisions'; do
    has_phrase SPEC.md "$pin" || fail "SPEC.md lost a decision: $pin"
    ok "${pin:0:64}"
  done

  section "the revision table answers every review finding with a verdict and evidence"
  has_phrase SPEC.md 'Revision 20 Oct 2026, after an independent review' ||
    fail "SPEC.md lost the revision table's title"
  for id in P0-1 P0-2 P0-3 P1-a P1-b P1-c P1-d P1-e P1-f P1-g P2-1 P2-2 P2-3 D-1 D-2; do
    row="$(grep -m1 "^| $id |" SPEC.md || true)"
    [ -n "$row" ] || fail "the revision table has no row for $id"
    printf '%s\n' "$row" | grep -qE '\*\*(ACCEPT|PARTIAL|REJECT|PROPOSED, not decided)\*\*' ||
      fail "the revision table's $id row has no verdict"
    if printf '%s\n' "$row" | grep -qF '<<'; then fail "the revision table's $id row still has an unfilled number"; fi
  done
  for id in D-1 D-2; do
    grep -m1 "^| $id |" SPEC.md | grep -qF 'PROPOSED, not decided' ||
      fail "$id must stay marked as proposed, not decided, until the owner confirms it"
  done
  ok "fifteen findings, each with a verdict; the two defaults are marked proposed"

  section "no fallback mode, and no workspace-lifetime claim, outside the revision table"
  if grep -n 'own_list\|CHECK_MODE' SPEC.md | grep -v '^[0-9]*:| P0-3 |'; then
    fail "SPEC.md still names the removed own_list fallback outside the revision table"
  fi
  if grep -nE 'hours of inactivity|idle timeout|7200|WORKSPACE_TTL' SPEC.md | grep -v '^[0-9]*:| P1-d |'; then
    fail "SPEC.md still makes a workspace-lifetime claim outside the revision table"
  fi
  ok "own_list appears only in the P0-3 row; no idle-timeout claim outside the P1-d row"

  section "no overlap with the sibling entry's wording, headings or names"
  # Method: each paragraph (blank-line separated, 20 words or more; fenced code, block quotes and the
  # SPEC's submission checklist excluded) of this entry's README and docs/submission.md is compared
  # with every such paragraph of the sibling's README and docs/submission.md. Similarity is
  # difflib.SequenceMatcher's ratio over the two lower-cased word lists. Any paragraph at 0.60 or
  # more fails; so does any heading the two share, except Devpost's own form fields. The SPEC is
  # held to 0.75 (it quotes the same Rules and describes the same hosting), and may share no module
  # name (besides __main__.py), test file name, or tool and verb name with the sibling's SPEC.
  sibling_dir=../open-slot
  if [ -f "$sibling_dir/README.md" ] && [ -f "$sibling_dir/docs/submission.md" ] && [ -f "$sibling_dir/SPEC.md" ]; then
    "${PY:-python3}" -I - README.md docs/submission.md SPEC.md \
      "$sibling_dir/README.md" "$sibling_dir/docs/submission.md" "$sibling_dir/SPEC.md" <<'PYEOF' ||
import difflib, os, re, sys

PROSE_MAX = 0.60
SPEC_MAX = 0.75
MIN_WORDS = 20
SPEC_SKIP = ('13. Submission checklist',)
FORM_HEADINGS = {
    'project name', 'elevator pitch', 'about the project', 'built with', 'try it out links',
    'video demo link', 'testing instructions', 'inspiration', 'what it does', 'how we built it',
    'challenges we ran into', 'accomplishments that we re proud of', 'what we learned',
    'license',
}


def words(text):
    text = re.sub(r'[`*_>|#\[\]()]', ' ', text.lower())
    return re.findall(r"[a-z0-9']+", text)


def blocks(path, skip_sections=()):
    out, cur, heads, in_code, section = [], [], [], False, ''

    def flush():
        if cur:
            out.append(' '.join(cur))
            cur.clear()

    with open(path, encoding='utf-8') as fh:
        for line in fh.read().split('\n'):
            if line.startswith('```'):
                flush()
                in_code = not in_code
                continue
            if in_code:
                continue
            m = re.match(r'^(#+)\s+(.*)$', line)
            if m:
                flush()
                heads.append(re.sub(r'\W+', ' ', m.group(2).lower()).strip())
                if len(m.group(1)) == 2:
                    section = m.group(2)
                continue
            if any(s in section for s in skip_sections) or line.startswith('> '):
                continue
            if not line.strip():
                flush()
                continue
            cur.append(line.strip())
    flush()
    return [words(b) for b in out if len(words(b)) >= MIN_WORDS], heads


def best_ratio(mine, theirs, floor):
    best = 0.0
    for other in theirs:
        a, b = len(mine), len(other)
        if min(a, b) / max(a, b) < floor:
            continue
        sm = difflib.SequenceMatcher(None, mine, other, autojunk=False)
        if sm.real_quick_ratio() < floor or sm.quick_ratio() < floor:
            continue
        best = max(best, sm.ratio())
    return best


def compare(mine_paths, theirs_paths, skip=(), floor=0.5):
    theirs, their_heads = [], set()
    for p in theirs_paths:
        b, h = blocks(p, skip)
        theirs += b
        their_heads |= set(h)
    scores, same_heads, n_heads = [], [], 0
    for p in mine_paths:
        b, h = blocks(p, skip)
        scores += [(best_ratio(x, theirs, floor), os.path.basename(p), ' '.join(x[:12])) for x in b]
        for head in h:
            n_heads += 1
            if head in their_heads and head not in FORM_HEADINGS:
                same_heads.append(head)
    return scores, same_heads, n_heads


def names(spec, pattern, start=None, stop=None):
    text = open(spec, encoding='utf-8').read()
    if start:
        text = text[text.index(start):]
    if stop and stop in text:
        text = text[:text.index(stop)]
    return set(re.findall(pattern, text, flags=re.M))


def main(argv):
    mine_readme, mine_sub, mine_spec, sib_readme, sib_sub, sib_spec = argv[1:7]
    failures = []

    scores, same, n_heads = compare([mine_readme, mine_sub], [sib_readme, sib_sub])
    over = [s for s in scores if s[0] >= PROSE_MAX]
    print('  README and submission: %d paragraphs; highest similarity %.2f; at or above %.2f: %d'
          % (len(scores), max(s[0] for s in scores), PROSE_MAX, len(over)))
    print('  README and submission headings: %d; identical to the sibling\'s, form fields excepted: %d'
          % (n_heads, len(same)))
    for s in sorted(over, reverse=True)[:8]:
        print('    %.2f %s: %s' % s)
        failures.append('a paragraph is %.2f similar to the sibling\'s' % s[0])
    for head in same:
        print('    heading: ' + head)
        failures.append('heading shared with the sibling: ' + head)

    scores, _, _ = compare([mine_spec], [sib_spec], SPEC_SKIP, floor=SPEC_MAX - 0.05)
    over = [s for s in scores if s[0] >= SPEC_MAX]
    print('  SPEC: %d paragraphs outside quotes and the checklist; highest similarity %.2f; at or above %.2f: %d'
          % (len(scores), max(s[0] for s in scores), SPEC_MAX, len(over)))
    for s in sorted(over, reverse=True)[:8]:
        print('    %.2f %s: %s' % s)
        failures.append('a SPEC paragraph is %.2f similar to the sibling\'s' % s[0])

    tree = r'[├└]── ([a-z_0-9]+\.py)'
    shared_mod = (names(mine_spec, tree) & names(sib_spec, tree)) - {'__main__.py'}
    shared_test = names(mine_spec, r'`(test_[a-z_0-9]+\.py)`') & names(sib_spec, r'`(test_[a-z_0-9]+\.py)`')
    row = r'^\| `([a-z_]+)` \|'
    mine_tools = names(mine_spec, row, '## 5. Tool list', '## 6. ')
    sib_tools = names(sib_spec, row, '## 5. Tool list', '## 6. ')
    shared_tool = mine_tools & sib_tools
    print('  module names shared (besides __main__.py): %d; test file names shared: %d; '
          'tool and verb names shared: %d' % (len(shared_mod), len(shared_test), len(shared_tool)))
    for label, found in (('module', shared_mod), ('test file', shared_test), ('tool or verb', shared_tool)):
        for n in sorted(found):
            print('    shared %s: %s' % (label, n))
            failures.append('shared %s name: %s' % (label, n))

    if failures:
        print('overlap: ' + '; '.join(failures[:6]))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
PYEOF
      fail "this entry's wording or names overlap the sibling entry's beyond the stated thresholds"
    ok "README and submission under 0.60 per paragraph, SPEC under 0.75, no shared heading or name"
  else
    echo "  skip: the sibling entry is not in this tree"
  fi

  section "the plan itself makes no price or sales claim, and carries the kit's six items"
  if grep -nE 'costs less|sells better|cheaper|more available|price has moved|before it peaks' SPEC.md; then
    fail "SPEC.md makes a price, availability or sales claim the honesty rules forbid"
  fi
  kit_block="$(awk '/^\*\*Qloo.s own submission guide/ { on = 1 } /^\*\*This entry.s own final check/ { on = 0 } on' SPEC.md)"
  [ -n "$kit_block" ] || fail "SPEC.md section 13 lost the block mapping the kit's submission guide"
  for n in 1 2 3 4 5 6; do
    printf '%s\n' "$kit_block" | grep -q -- "^- \[ \] $n\. " || fail "the kit block lacks its item $n"
  done
  ok "no forbidden claim; the kit's six items are each mapped in section 13"
fi

if [ -f common_ground/__init__.py ]; then
  PY="${PY:-python3}"
  section "compile and test (no third-party packages, nothing to install)"
  "$PY" -W error -m compileall -q common_ground tests || fail "compileall found a problem"
  "$PY" -m unittest discover -s tests -t . -q || fail "the tests failed"
fi

echo "common-ground: all checks passed."
