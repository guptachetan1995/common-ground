# Qloo API notes

**Live calibration has not been done.** No Qloo key existed when this was written, so nothing below has been checked
against a real response. Every row says what Qloo's documentation shows and is marked *documented, not measured*.
The key-day probe (`python3 -m common_ground probe`) is the one thing that changes that: it makes at most 14 calls,
prints only paths, types, counts, status codes and pass or fail, and then prints a block for `common_ground/measured.py`.
Until the probe has run and that block is in place, the live source refuses every request with `shapes_unverified`, so
no live path rests on a guess.

This file holds shapes and thresholds and never a value. Qloo's developer guide says not to store its response data
in a public repository, so no entity id, name, score or tag from a response is written here or anywhere in this
tree, and a test fails if an id of Qloo's form turns up.

## Base and key

| Item | What the app does | Status |
|---|---|---|
| Base URL | `https://hackathon.api.qloo.com`, nothing else | documented, not measured |
| Key | Sent in the `X-Api-Key` header only. Never in a URL, a log line, a page or a trace. A redirect is never followed, because it would carry the header to another host | documented, not measured |
| Error classes | 401 is `qloo_auth`, 403 `qloo_unsupported_type`, 429 `qloo_rate_limited`, 5xx and 3xx `qloo_unavailable`, anything else `qloo_bad_request`. A 429 or a 5xx is retried at most twice, after 1 s and then 3 s | status mapping documented; the body shape of a 403 is not measured |

## The shapes the app reads

`records.py` is the only module that reads a response. It refuses a shape the documentation did not describe with
`qloo_unexpected_shape`, naming the JSON path and never a value, and treats an empty list as `qloo_no_results`.

| Reader | Request | Path | Type | Status |
|---|---|---|---|---|
| `read_search` | `GET /search` with `query`, `types`, `take` | `$.results[]` | list | documented, not measured |
| | | `$.results[].entity_id`, `.name`, `.type` | string, required | documented, not measured |
| | | `$.results[].popularity` | number, optional | documented, not measured |
| | | `$.results[].disambiguation` | string, optional | documented, not measured |
| `read_tags` | `GET /v2/tags` with `filter.query` | `$.results.tags[]` | list | documented, not measured |
| | | `$.results.tags[].id`, `.name` | string, required | documented, not measured |
| | | `$.results.tags[].type` | string, optional | documented, not measured |
| `read_group_search` | `GET /v2/insights`, place type, everyone's favourites | `$.results.entities[]` | list, its order is the position | documented, not measured |
| | | `.entity_id`, `.name` | string, required | documented, not measured |
| | | `.type`, `.subtype` | string, optional | documented, not measured |
| | | `.tags[]` with `id`, `name`, optional `type` | list | documented, not measured |
| | | `.properties.address`, `.properties.website` | string, optional | documented, not measured |
| | | aggregate explainability at the path `measured.LEAN_PATH` names | object holding a list `signal.interests.entities` of `entity_id` and `score` | path documented, not measured |
| `read_ranking` | `GET /v2/insights`, one person's favourites, `filter.results.entities` set to the long list | `$.results.entities[]` | the long list in that person's order | documented, not measured |
| | | `.entity_id` | string, required | documented, not measured |
| | | affinity at the path `measured.AFFINITY_PATH` names | number from 0 to 1, optional | path documented, not measured |
| | | explainability at the path `measured.EXPLAIN_PATH` names | the same list of `entity_id` and `score`, scores from 0 to 1 | path documented, not measured |

A ranking is read so that an id nobody asked for is counted and set aside, and an id returned twice counts once. The
app keeps from each result only the name, id, type, tags, address, website, its position, affinity and the
explainability scores. It never reads or sends anything about a person's identity or demographics.

## The thresholds the probe decides on

These are this entry's own pass marks, set before any call was made. None has been run.

| Threshold | Question | Pass | If it fails |
|---|---|---|---|
| T1 | Does a group search return places for a city? | At least 10 places with valid parameters, in the first city or else the second | The entry stops the same day |
| T2 | Do the conditions work? | The location filter changes the result, as `filter.location.query` or else `filter.geocode.name` | A day or price filter that does nothing is removed from the form, the README and the copy; a location that does nothing fails T1 |
| T3 | Can one request rank the long list for one person? | At least 80% of the requested ids come back, none that were not requested, in non-increasing affinity order when affinity is present, and two people's upper halves differ in at least 3 places, at 50 ids or else at 25 | The entry stops the same day. There is no fallback, because any substitute would make ranks that cannot be compared |
| T4 | Does the place type return explainability? | Present and non-empty | The "because" lines and the lean are removed; nothing else depends on it |
| T5 | Does the place type return affinity? | Present on each result | The bars are unchanged, since they come from rank; no number is shown, and the half-way tolerance falls back to two ranks |

## What the app fixes in code, not measured

- **Bands.** Above 0.8 is Very High, 0.6 to 0.8 High, below 0.5 Low; Qloo names none for 0.5 to 0.6, and the page
  then says nothing. These are the documentation's, not measured.
- **The half-way line.** The upper half of a ranking is the first half of the long list plus anything within 0.02
  of the half-way place's affinity (or within two ranks when there is no affinity). This is this app's rule, chosen
  because Qloo's guide to reading affinity says scores are normalised per query and should be read by position; the
  application of that advice to people is this entry's inference, not Qloo's statement. The probe records each
  person's smallest and largest affinity so the 0.02 can be checked against a real scale.
- **Explainability.** Only scores of 0.1 and above that name one of the person's own favourites are shown.

## Not yet measured, and what each would change

| Unknown | Where it lands when known |
|---|---|
| Whether `types` takes a comma-joined value or a repeated parameter | `measured.TYPES_FORM`, then `qloo_calls.py` |
| Which `types` values `/search` accepts for each domain | `measured.FAVOURITE_TYPES` |
| Which condition spellings change a result | `measured.CONDITIONS_OK` |
| The largest number of ids one ranking call accepts | `measured.LONG_LIST`, 50 or 25 |
| Where affinity and explainability sit in a result | `measured.AFFINITY_PATH`, `EXPLAIN_PATH`, `LEAN_PATH` |
| The body of a 403 | `wire.outcome_for`; the probe's last call, an unsupported `filter.type`, which its 14-call ceiling can leave out |
| Qloo's own per-key quota | the daily ceiling, which defaults to 300 and is lowered by hand if Qloo says less |
