"use strict";

const LOOPBACK = ["localhost", "127.0.0.1", "[::1]"];
const PLAIN_HTTP = location.protocol === "http:" && !LOOPBACK.includes(location.hostname);
const DISPATCH = "/api/dispatch";
const AS_AGENT = { "X-Common-Ground-As": "agent" };
const MAX_PEOPLE = 6;
const MIN_PEOPLE = 2;
const MAX_FAVOURITES = 3;
const PICKS_SHOWN = 5;
const POLL_MS = 500;
const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const LEVELS = [["", "Any"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]];

const SENTENCES = {
  live: "Live: Qloo is being called",
  synthetic: "Synthetic sample data. Qloo is not being called.",
  noKey: "No Qloo key is set on this server.",
  keySetOnSample: "A key is set, but this server was started on sample data.",
  unverified: "Live calls are refused until the key-day probe has checked Qloo's response shapes.",
  ceilingSample: "Daily ceiling spent: showing synthetic sample data.",
  ceilingSampleWhy: "This outing was opened after the server used its live Qloo calls for the day, so its places are invented and Qloo is not being called for it.",
  ceilingLive: "Daily ceiling spent: live Qloo calls are refused for this outing until the day changes (UTC) or the server restarts. It is never switched to sample data. A new outing runs on synthetic sample data, labelled as such.",
  ceilingNew: "Daily ceiling spent: live Qloo calls are refused today. A new outing runs on synthetic sample data, labelled as such.",
  plainHttp: "This page was loaded over plain HTTP, so your browser sends no label with its requests, and Resolve, Pick and Sign off cannot work here. Open the HTTPS address.",
  plainHttpNoWorkspace: "A workspace cannot be kept over plain HTTP: the cookie that holds it is for secure pages only, so the browser drops it. Open the HTTPS address.",
  plainHttpOrigin: "The server also refuses every request sent from here (bad_origin), because its own address is https.",
  noLabel: "Your browser does not label requests, so you cannot resolve a match or sign off here. Use a current Chrome, Firefox or Safari.",
  publicThings: "Type the names of public things only (a restaurant, a band, a film, a show, a book, a brand). Each name is sent to Qloo to find a match.",
  notComparable: "Scores from separate calls are not comparable between people.",
  notAPrediction: "Qloo's figures describe how its audiences relate to the things a person named. They are not a prediction about that person.",
  sendsNothing: "This app never sends a message, books a table or pays anyone. You send it yourself.",
};

const WORDS = {
  no_workspace: "This workspace is gone. The server restarted or woke from sleep, and a restart empties every workspace. Reload the page to start again; the sample button starts the sample again.",
  unreachable: "The server could not be reached. Check the connection and try again.",
  busy: "The server is busy with other requests. Try again in a moment.",
  rate_limited: "Too many requests in a minute. Wait a moment and try again.",
  over_limit: "This outing has used its Qloo call limit. Only the organiser can lift it.",
  agent_allowance_spent: "The agent has used its Qloo calls for the day. A person's own click still runs.",
  daily_ceiling_spent: "The server has used all of its live Qloo calls for today. An outing opened live is never switched to sample data.",
  shapes_unverified: "Live mode is on, but Qloo's response shapes have not been checked yet, so no live call runs.",
  no_key: "Live mode needs a Qloo key and none is set.",
  qloo_auth: "Qloo refused the key. The person running this server needs to check it.",
  qloo_rate_limited: "Qloo is limiting requests. Wait a moment and try again.",
  qloo_unavailable: "Qloo could not be reached. Try again in a moment.",
  qloo_bad_request: "Qloo did not accept the request.",
  qloo_unsupported_type: "Qloo does not support that kind of search.",
  qloo_unexpected_shape: "Qloo answered in a shape this app does not recognise.",
  qloo_no_results: "Qloo returned nothing for that search.",
  needs_favourites: "Every person needs at least one resolved match before places can be compared.",
  favourite_unresolved: "A favourite Qloo found candidates for still waits for someone to say which one was meant.",
  stale_comparison: "The matches or conditions changed since the last comparison. Compare again.",
  stale_revision: "The outing changed in the meantime. The page has been refreshed; try again.",
  left_out_unacknowledged: "Say who this place leaves out before picking it.",
  sender_missing: "Name the sender before signing a message off.",
  unknown_place: "That place is not on the current comparison.",
  unknown_draft: "That draft is gone.",
  unknown_tag: "That kind of place is not one Qloo returned for this outing.",
  unknown_entity: "That is not one of the candidates Qloo returned for this favourite.",
  bad_origin: "The server refused this request because it came from an address that is not its own.",
  cross_site: "The server refused a request that came from another site.",
  wrong_actor: "Only the organiser's own click can do that.",
  wrong_member: "This link can only resolve its own person's matches.",
  not_a_tool: "That is not something the agent can do.",
  too_many_favourites: "A person can have at most three favourites.",
  smuggled_field: "That tool does not take that argument.",
};

const DETAIL_WORDS = {
  label: "Give the outing a name of up to 60 characters.",
  place_text: "Give a city or neighbourhood of up to 60 characters.",
  members: "Add two to six people.",
  "members.name": "Each person needs a different name of 1 to 24 characters.",
  "members.favourites": "A favourite is 1 to 60 characters.",
  name: "A favourite is 1 to 60 characters.",
  price_min: "The lowest price level cannot be above the highest.",
  price_max: "Price levels run from 1 to 4.",
  when: "The time can be up to 40 characters.",
  kind_query: "The kind of place is one short word.",
  query: "The kind of place is one short word.",
  reason: "Give a reason of up to 200 characters.",
  sender_name: "Name the sender, in 1 to 60 characters.",
  limit: "Choose a limit above the current one, up to 60.",
};

const HEADLINES = {
  common: (n) => (n === 1
    ? "One place is in the upper half of every ranked person's own ranking."
    : `${n} places are in the upper half of every ranked person's own ranking.`),
  none_shared: () => "No place is shared by everyone. The closest places below name who each one leaves out.",
  none_close: (n, who) => `No place comes close: ${who} ranked only part of the long list, so most places count as outside most people's upper halves.`,
  thin_list: () => "Too few places came back to compare people, so nothing was ranked.",
  unranked: () => "Places were found, but nobody has been ranked yet.",
};

const STOPS = {
  done: "Every person was ranked.",
  no_common_ground: "It stopped early, because no place can be shared by everyone any more.",
  thin_list: "It stopped because too few places came back.",
  over_limit: "It stopped at the outing's call limit.",
  agent_allowance_spent: "It stopped at the agent's daily allowance.",
  daily_ceiling_spent: "It stopped at the server's daily ceiling.",
  qloo_refused: "It stopped because Qloo refused requests.",
};

const BANDS = "Qloo's band";

class Problem extends Error {
  constructor(code, detail) {
    super(code);
    this.code = code;
    this.detail = detail || "";
  }
}

const state = {
  data: null,
  calls: [],
  tools: [],
  busy: false,
  planning: false,
  gate: false,
  banners: "",
  choices: new Map(),
  kindChoice: undefined,
  fields: new Map(),
  acks: new Map(),
  open: new Set(),
  console: { tool: "", args: "", status: "", output: "" },
};
let page = null;

const $ = (selector, root = document) => root.querySelector(selector);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === false || value == null) continue;
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (typeof value === "boolean") {
      if (key in node) node[key] = value;
      else node.setAttribute(key, "");
    } else node.setAttribute(key, value);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
}

function initial(name) {
  const letter = (name || "").trim().charAt(0);
  return letter ? letter.toUpperCase() : "?";
}

function kindOf(type) {
  return String(type || "").split(":").pop().replace(/_/g, " ");
}

function listOf(names) {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function capital(text) {
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`;
}

function sentence(text) {
  const plain = String(text).trim();
  if (!plain) return "";
  const cap = capital(plain);
  return /[.!?]$/.test(cap) ? cap : `${cap}.`;
}

function safeUrl(value) {
  return /^https?:\/\//i.test(value || "") ? value : null;
}

/* ---- the network ---- */

async function request(method, path, body, headers) {
  let response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(headers || {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Problem("unreachable");
  }
  let json = null;
  try {
    json = await response.json();
  } catch {
    json = null;
  }
  return { status: response.status, json, retryAfter: Number(response.headers.get("Retry-After")) || 0 };
}

async function load(path) {
  const reply = await request("GET", path);
  if (reply.status === 401) throw new Problem("no_workspace");
  if (reply.status !== 200 || !reply.json) throw new Problem((reply.json && reply.json.outcome) || `http_${reply.status}`);
  return reply.json;
}

async function waitOut(seconds) {
  for (let left = seconds; left > 0; left -= 1) {
    setStatus(`Too many requests in a minute. Waiting ${left} s before trying again.`);
    await sleep(1000);
  }
}

async function act(path, tool, args) {
  for (let attempt = 0; ; attempt += 1) {
    const reply = await request("POST", path, { tool, args });
    if (reply.status === 429 && attempt < 3) {
      await waitOut(reply.retryAfter || 5);
      continue;
    }
    const json = reply.json;
    if (reply.status !== 200 || !json) throw new Problem((json && json.outcome) || `http_${reply.status}`);
    if (!json.ok) throw new Problem(json.outcome, json.error && json.error.detail);
    return json.result;
  }
}

function say(problem) {
  if (problem.code === "no_workspace" && PLAIN_HTTP) return SENTENCES.plainHttpNoWorkspace;
  const base = WORDS[problem.code];
  const detail = DETAIL_WORDS[problem.detail];
  if (problem.code === "bad_arguments") return detail || `A value was not accepted${problem.detail ? ` (${problem.detail})` : ""}.`;
  if (base) return base;
  return `Refused: ${problem.code}${problem.detail ? ` (${problem.detail})` : ""}.`;
}

function setStatus(text) {
  $("#status").textContent = text;
}

function clearProblem() {
  const box = $("#problem");
  box.hidden = true;
  box.replaceChildren();
}

function showProblem(problem) {
  const box = $("#problem");
  box.hidden = false;
  box.replaceChildren(el("p", { class: "banner alert", text: say(problem) }));
}

/* ---- banners and the gate ---- */

function sourceWord(out) {
  return out.source === "synthetic" ? "the sample data" : "Qloo";
}

function banner(tone, ...kids) {
  return el("p", { class: `banner ${tone}` }, ...kids);
}

function gateBroken(data) {
  return PLAIN_HTTP || data.actor !== "person";
}

function modeBanners(mode, outing) {
  if (!mode) return [];
  if (mode.source !== "live") {
    return [banner("warn", el("strong", { text: SENTENCES.synthetic }),
      ` ${mode.key === "set" ? SENTENCES.keySetOnSample : SENTENCES.noKey}`)];
  }
  const shown = [];
  if (outing && outing.source === "synthetic") {
    shown.push(banner("warn", el("strong", { text: SENTENCES.ceilingSample }), ` ${SENTENCES.ceilingSampleWhy}`));
  } else if (mode.ceilingSpent) {
    shown.push(banner(outing ? "alert" : "warn", outing ? SENTENCES.ceilingLive : SENTENCES.ceilingNew));
  } else {
    shown.push(banner("good", el("strong", { text: `${SENTENCES.live} (key: ${mode.key})` })));
  }
  if (!mode.shapesVerified) shown.push(banner("warn", SENTENCES.unverified));
  return shown;
}

function renderBanners(data, outing) {
  const shown = data ? modeBanners(data.mode, outing) : [];
  if (PLAIN_HTTP) shown.push(banner("alert", `${SENTENCES.plainHttp} ${SENTENCES.plainHttpOrigin}`));
  else if (data && data.actorWhy === "no_fetch_metadata") shown.push(banner("alert", SENTENCES.noLabel));
  const signature = shown.map((node) => node.textContent).join("|");
  if (signature === state.banners) return;
  state.banners = signature;
  $("#banners").replaceChildren(...shown);
}

function syncButtons() {
  for (const button of document.querySelectorAll("main button")) {
    const person = button.hasAttribute("data-needs-person") && state.gate;
    button.disabled = person || button.hasAttribute("data-not-ready");
  }
}

function bindReady(button, ready, inputs) {
  const update = () => {
    button.toggleAttribute("data-not-ready", !ready());
    syncButtons();
  };
  for (const input of inputs) {
    input.addEventListener("input", update);
    input.addEventListener("change", update);
  }
  update();
}

function enterPresses(input, button) {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !button.disabled) button.click();
  });
}

function focusHeading(id) {
  const heading = document.getElementById(id);
  if (heading) heading.focus();
}

function focusKey(key) {
  const target = document.querySelector(`[data-focus="${CSS.escape(key)}"]:not(:disabled)`);
  if (target) target.focus();
  return Boolean(target);
}

function moveOnFrom(memberId) {
  const blocks = [...document.querySelectorAll("#match-list .person")];
  const here = blocks.findIndex((block) => block.querySelector(`[data-focus="resolve:${memberId}"]`));
  const next = blocks[here + 1];
  const target = next && next.querySelector("input:checked, button:not(:disabled)");
  if (target) target.focus();
  else focusHeading("h-kind");
}

async function run(task, options) {
  if (state.busy) return;
  state.busy = true;
  document.body.setAttribute("aria-busy", "true");
  clearProblem();
  const stopWatching = options && options.watch ? watchCalls() : () => {};
  let failed = false;
  try {
    await task();
  } catch (error) {
    failed = true;
    const problem = error instanceof Problem ? error : new Problem("unexpected", error && error.message);
    if (!(error instanceof Problem)) console.error(error);
    showProblem(problem);
    if (problem.code !== "no_workspace" && problem.code !== "unreachable") {
      try {
        await refresh();
      } catch {
        /* the problem above stands */
      }
    }
  } finally {
    stopWatching();
    state.busy = false;
    document.body.removeAttribute("aria-busy");
    if (failed) setStatus("");
  }
}

async function refresh() {
  state.data = await load(page.statePath);
  if (page.extra) await page.extra();
  page.render();
}

function watchCalls() {
  let watching = true;
  const timer = setInterval(async () => {
    try {
      const json = await load("/api/calls");
      if (watching) {
        state.calls = json.calls;
        renderStrip();
      }
    } catch {
      /* the run reports its own problem */
    }
  }, POLL_MS);
  return () => {
    watching = false;
    clearInterval(timer);
  };
}

/* ---- small building blocks ---- */

function disclosure(key, title, ...kids) {
  const node = el("details", {}, el("summary", { text: title }), ...kids);
  node.open = state.open.has(key);
  node.addEventListener("toggle", () => {
    if (node.open) state.open.add(key);
    else state.open.delete(key);
  });
  return node;
}

function remember(key, input) {
  if (state.fields.has(key)) input.value = state.fields.get(key);
  input.addEventListener("input", () => state.fields.set(key, input.value));
  return input;
}

function selectField(key, id, label, options, current) {
  const select = el("select", { id, "data-focus": key },
    options.map(([value, text]) => el("option", { value, text })));
  select.value = state.fields.has(key) ? state.fields.get(key) : current;
  select.addEventListener("change", () => state.fields.set(key, select.value));
  return { select, field: el("div", { class: "field" }, el("label", { for: id, text: label }), select) };
}

async function copyField(input, note) {
  try {
    await navigator.clipboard.writeText(input.value);
    note.textContent = "Copied.";
  } catch {
    input.focus();
    input.select();
    note.textContent = "Copying was blocked here. The text is selected: press Ctrl+C (Cmd+C on a Mac).";
  }
}

function copyRow(id, label, value) {
  const input = el("input", { id, type: "text", readonly: true, value, "aria-describedby": `${id}-note` });
  const note = el("p", { class: "copy-note", id: `${id}-note`, role: "status" });
  const button = el("button", { type: "button", "data-focus": `copy:${id}`, onclick: () => copyField(input, note) },
    "Copy");
  return el("div", { class: "link-row" },
    el("label", { for: id, class: "field-label", text: label }),
    el("div", { class: "copy-line" }, input, button),
    note);
}

/* ---- the favourites of one person: candidates, and the person's choice ---- */

function chosenFor(member, favourite) {
  const key = `${member.id}:${favourite.id}`;
  return state.choices.get(key) ?? favourite.resolved ?? (favourite.candidates[0] && favourite.candidates[0].entityId);
}

function candidateName(favourite, entityId) {
  const found = favourite.candidates.find((c) => c.entityId === entityId);
  return found ? found.name : "";
}

function provenance(member, favourite) {
  if (!favourite.resolved) return null;
  const by = favourite.resolvedBy === "organiser_for"
    ? `resolved by the organiser for ${member.name}`
    : `resolved by ${member.name}`;
  return `Matched to ${candidateName(favourite, favourite.resolved)} (${by}).`;
}

function favouriteBlock(member, favourite, canSearch) {
  const key = `${member.id}:${favourite.id}`;
  const legend = `Which one did ${member.name} mean by “${favourite.name}”?`;
  const box = el("fieldset", { class: "favourite" }, el("legend", { text: legend }));
  if (favourite.namedBy === "organiser_for") {
    box.append(el("p", { class: "provenance", text: `Added by the organiser for ${member.name}.` }));
  }
  if (!favourite.candidates.length) {
    const found = favourite.searched
      ? `Qloo found nothing for “${favourite.name}”, so it is not used.`
      : `“${favourite.name}” has not been searched yet, so it is not used.`;
    box.append(el("p", { class: "empty", text: found }));
    if (canSearch) {
      box.append(el("button", {
        type: "button",
        "data-focus": `search:${key}`,
        onclick: () => searchOne(member, favourite),
      }, favourite.searched ? "Search Qloo again" : "Search Qloo for this favourite"));
    } else if (!favourite.searched) {
      box.append(el("p", { class: "provenance", text: "The organiser's page runs the Qloo search for it. Check again in a moment." }),
        el("button", {
          type: "button",
          "data-focus": `check:${key}`,
          onclick: () => run(async () => {
            await refresh();
            setStatus("Checked for a Qloo search.");
          }),
        }, "Check again"));
    }
    return box;
  }
  const selected = chosenFor(member, favourite);
  for (const candidate of favourite.candidates) {
    box.append(el("label", { class: "choice" },
      el("input", {
        type: "radio",
        name: `pick-${key}`,
        value: candidate.entityId,
        checked: candidate.entityId === selected,
        "data-focus": `radio:${key}:${candidate.entityId}`,
        onchange: () => {
          state.choices.set(key, candidate.entityId);
          page.render();
        },
      }),
      el("span", { class: "choice-text" },
        el("strong", { text: candidate.name }),
        " ",
        el("span", { class: "kind", text: kindOf(candidate.type) }),
        candidate.disambiguation ? el("span", { class: "note", text: candidate.disambiguation }) : null)));
  }
  const said = provenance(member, favourite);
  box.append(el("p", {
    class: "provenance",
    text: said || "Not matched yet. Choose the one meant, then press Resolve.",
  }));
  return box;
}

function personHead(member, index, role) {
  return el("div", { class: "person-head" },
    el("span", { class: `disc hue-${index % 6}`, "aria-hidden": "true", text: initial(member.name) }),
    el("h3", {}, member.name, role ? el("span", { class: "role", text: ` ${role}` }) : null));
}

function resolveButton(member, favourites, dispatchPath, outingId) {
  const open = favourites.filter((f) => f.candidates.length);
  const unchanged = open.every((f) => f.resolved && f.resolved === chosenFor(member, f));
  return el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": `resolve:${member.id}`,
    "data-not-ready": open.length === 0 || unchanged,
    onclick: () => run(async () => {
      for (const f of open) {
        const pick = chosenFor(member, f);
        if (pick === f.resolved) continue;
        setStatus(`Recording ${member.name}'s match for “${f.name}”`);
        await act(dispatchPath, "resolve_match", {
          outing_id: outingId, member_id: member.id, favourite_id: f.id, entity_id: pick,
        });
      }
      setStatus(`${member.name}'s matches are recorded.`);
      await refresh();
      if (page.moveOn) page.moveOn(member.id);
    }),
  }, `Resolve ${member.name}'s matches`);
}

function addFavouriteBox(member, outingId, path, label, searchesToo) {
  if (member.favourites.length >= MAX_FAVOURITES) return null;
  const id = `add-${member.id}`;
  const input = remember(`fav:${member.id}`, el("input", {
    id, type: "text", maxlength: "60", autocomplete: "off", "aria-describedby": `${id}-hint`,
    "data-focus": `add:${member.id}`,
  }));
  const button = el("button", {
    type: "button",
    "data-needs-person": true,
    "data-focus": `add-go:${member.id}`,
    onclick: () => run(async () => {
      const name = input.value.trim();
      setStatus(`Adding “${name}” for ${member.name}`);
      const added = await act(path, "add_own_favourite", { outing_id: outingId, member_id: member.id, name });
      state.fields.delete(`fav:${member.id}`);
      if (searchesToo) {
        setStatus(`Asking Qloo what “${name}” could mean`);
        await act(DISPATCH, "look_up_favourite", {
          outing_id: outingId, member_id: member.id, favourite_id: added.favouriteId,
        });
      }
      await refresh();
      setStatus(searchesToo
        ? `“${name}” was added and Qloo proposed matches. Say which one was meant.`
        : `“${name}” was added. The organiser's page runs the Qloo search for it.`);
      if (!focusKey(`add:${member.id}`)) focusHeading(page.top);
    }),
  }, "Add");
  bindReady(button, () => input.value.trim().length > 0, [input]);
  enterPresses(input, button);
  return el("div", { class: "field add-favourite" },
    el("label", { for: id, text: label }),
    el("p", { class: "hint", id: `${id}-hint`, text: SENTENCES.publicThings }),
    el("div", { class: "copy-line" }, input, button));
}

/* ---- the organiser's page ---- */

const latest = () => (state.data && state.data.outings.length ? state.data.outings[state.data.outings.length - 1] : null);

function renderSummary(out) {
  const c = out.conditions;
  const price = c.priceMin == null && c.priceMax == null
    ? "any price level"
    : `price level ${c.priceMin ?? 1} to ${c.priceMax ?? 4}`;
  const rows = [
    ["Outing", out.label],
    out.when ? ["When", out.when] : null,
    ["Day", capital(c.day)],
    ["City", c.placeText],
    ["Price", price],
    ["Kind of place", c.kindTag ? c.kindTag.name : "not chosen yet"],
    ["People", listOf(out.members.map((m) => m.name))],
    ["Data", out.source === "synthetic" ? "synthetic sample data" : "live Qloo calls"],
    ["Qloo calls", `${out.budget.spent} of ${out.budget.limit} used`],
  ].filter(Boolean);
  $("#summary-body").replaceChildren(el("dl", { class: "facts" },
    rows.flatMap(([term, detail]) => [el("dt", { text: term }), el("dd", { text: detail })])));
}

function renderConditions(out) {
  const c = out.conditions;
  const day = selectField("cond:day", "c-day", "Day", DAYS.map((d) => [d, capital(d)]), c.day);
  const low = selectField("cond:min", "c-min", "Lowest price level", LEVELS, c.priceMin == null ? "" : String(c.priceMin));
  const high = selectField("cond:max", "c-max", "Highest price level", LEVELS, c.priceMax == null ? "" : String(c.priceMax));
  const city = remember("cond:city", el("input", {
    id: "c-city", type: "text", maxlength: "60", value: c.placeText, "data-focus": "cond:city",
  }));
  if (!state.fields.has("cond:city")) city.value = c.placeText;
  const wanted = () => {
    const changes = {};
    if (day.select.value !== c.day) changes.day = day.select.value;
    const cityText = city.value.trim();
    if (cityText && cityText !== c.placeText) changes.place_text = cityText;
    const min = low.select.value === "" ? null : Number(low.select.value);
    const max = high.select.value === "" ? null : Number(high.select.value);
    if (min !== c.priceMin) changes.price_min = min;
    if (max !== c.priceMax) changes.price_max = max;
    return changes;
  };
  const apply = el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": "cond:apply",
    onclick: () => run(async () => {
      const now = latest();
      setStatus("Changing the conditions");
      await act(DISPATCH, "change_conditions", { outing_id: now.id, ...wanted() });
      for (const key of ["cond:day", "cond:min", "cond:max", "cond:city"]) state.fields.delete(key);
      await refresh();
      setStatus("The conditions are changed. The comparison is out of date, so compare again.");
      if (!focusKey("compare")) focusHeading("h-compare");
    }),
  }, "Change the conditions");
  bindReady(apply, () => Object.keys(wanted()).length > 0 && city.value.trim().length > 0,
    [day.select, low.select, high.select, city]);
  $("#conditions-body").replaceChildren(disclosure("conditions", "Change the day, the price or the city",
    el("p", { class: "hint", text: "Only you can change a condition, and the agent has no tool for it. A comparison made before the change is marked out of date. Price levels are Qloo's 1 to 4 scale, not an amount of money." }),
    el("div", { class: "grid-3" }, day.field, low.field, high.field),
    el("div", { class: "field" }, el("label", { for: "c-city", text: "City or neighbourhood" }), city),
    el("div", { class: "actions" }, apply)));
}

function renderMatch(out, data) {
  const links = (data.memberLinks && data.memberLinks[out.id]) || {};
  const blocks = out.members.map((member, index) => {
    const block = el("div", { class: "person" },
      personHead(member, index, index === 0 ? "(organiser)" : ""),
      ...member.favourites.map((f) => favouriteBlock(member, f, true)),
      resolveButton(member, member.favourites, DISPATCH, out.id),
      addFavouriteBox(member, out.id, DISPATCH, `Add a favourite for ${member.name}`, true));
    if (!member.favourites.length) {
      block.insertBefore(el("p", { class: "empty", text: `${member.name} has no favourites yet, so cannot be compared. Add one below.` }),
        block.children[1]);
    }
    if (index > 0 && links[member.id]) {
      block.append(copyRow(`link-${member.id}`, `${member.name}'s own link, to resolve these from their phone`, links[member.id]));
    }
    return block;
  });
  $("#match-list").replaceChildren(...blocks);
}

function renderKind(out) {
  const body = $("#kind-body");
  const current = out.conditions.kindTag;
  const note = current
    ? el("p", { class: "provenance", text: `Chosen: ${current.name}.` })
    : el("p", { class: "provenance", text: "No kind chosen yet. Without one, the search covers every kind of place Qloo lists." });
  const word = el("input", { id: "kind-word", type: "text", maxlength: "60", value: out.kindQuery || "" });
  const search = el("button", {
    type: "button",
    "data-focus": "kind:search",
    onclick: () => run(async () => {
      const text = word.value.trim();
      if (!text) throw new Problem("bad_arguments", "query");
      setStatus(`Asking Qloo for kinds of place matching “${text}”`);
      await act(DISPATCH, "look_up_kind", { outing_id: out.id, query: text });
      state.kindChoice = undefined;
      await refresh();
    }),
  }, "Search for kinds");
  enterPresses(word, search);
  const searchBox = el("div", { class: "field" },
    el("label", { for: "kind-word", text: "Search Qloo for a kind of place" }),
    word,
    el("div", { class: "actions" }, search));
  if (!out.knownTags.length) {
    body.replaceChildren(note, searchBox);
    return;
  }
  const selected = state.kindChoice !== undefined ? state.kindChoice : current ? current.id : "";
  const options = [{ id: "", name: "Any kind of place" }, ...out.knownTags];
  const group = el("fieldset", { class: "favourite" }, el("legend", { text: "Which kind of place?" }),
    ...options.map((tag) => el("label", { class: "choice" },
      el("input", {
        type: "radio", name: "kind", value: tag.id, checked: tag.id === selected,
        "data-focus": `kind-radio:${tag.id}`,
        onchange: () => {
          state.kindChoice = tag.id;
          page.render();
        },
      }),
      el("span", { class: "choice-text" }, el("strong", { text: tag.name })))));
  const use = el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": "kind:use",
    "data-not-ready": (current ? current.id : "") === selected,
    onclick: () => run(async () => {
      await act(DISPATCH, "change_conditions", { outing_id: out.id, kind_tag: selected || null });
      state.kindChoice = undefined;
      setStatus("The kind of place is recorded.");
      await refresh();
      const next = document.querySelector('[data-focus="compare"]:not(:disabled)');
      if (next) next.focus();
      else focusHeading("h-compare");
    }),
  }, "Use this kind");
  body.replaceChildren(note, group, el("div", { class: "actions" }, use),
    el("details", {}, el("summary", { text: "Search for a different word" }), searchBox));
}

function waitingFor(out) {
  return out.members
    .filter((m) => !m.favourites.some((f) => f.resolved) || m.favourites.some((f) => f.candidates.length && !f.resolved))
    .map((m) => m.name);
}

function unsearched(out) {
  return out.members.flatMap((m) => m.favourites.filter((f) => !f.searched).map((f) => `${m.name}'s “${f.name}”`));
}

function liftControl(out) {
  const b = out.budget;
  const max = state.data.callLimit.max;
  if (b.limit >= max) {
    return el("p", { class: "hint", text: `The call limit is already at its most, ${max}.` });
  }
  const steps = [];
  for (let v = b.limit + 5; v < max; v += 5) steps.push(v);
  steps.push(max);
  const choice = selectField("lift", "lift-limit", "New limit for this outing", steps.map((v) => [String(v), String(v)]), String(steps[0]));
  const button = el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": "lift:go",
    onclick: () => run(async () => {
      const now = latest();
      await act(DISPATCH, "lift_call_limit", { outing_id: now.id, limit: Number(choice.select.value) });
      state.fields.delete("lift");
      await refresh();
      setStatus(`The limit is now ${latest().budget.limit}. Compare again to carry on.`);
      if (!focusKey("compare")) focusHeading("h-compare");
    }),
  }, "Raise the limit");
  return el("div", { class: "lift" }, choice.field, el("div", { class: "actions" }, button));
}

function renderCompare(out) {
  const waiting = waitingFor(out);
  const idle = unsearched(out);
  const c = out.comparison;
  const b = out.budget;
  const spentAll = b.spent >= b.limit;
  const label = c ? "Compare again" : "Compare places";
  const parts = [
    waiting.length
      ? el("p", { class: "provenance", text: `Waiting for ${listOf(waiting)} to say which match they meant.` })
      : el("p", { class: "provenance", text: "Everyone has a resolved match. The comparison makes one group search, then one ranking per person." }),
  ];
  if (idle.length) {
    parts.push(el("p", { class: "provenance", text: `Not searched yet, so not used: ${listOf(idle)}.` }));
  }
  const buttons = [el("button", {
    type: "button",
    class: "primary",
    "data-focus": "compare",
    "data-not-ready": waiting.length > 0,
    onclick: () => compare(out, false),
  }, label)];
  if (c && !c.stale && !c.complete && c.stoppedBecause === "no_common_ground") {
    buttons.push(el("button", {
      type: "button", "data-focus": "compare-all", onclick: () => compare(out, true),
    }, "Rank everyone anyway"));
  }
  const budget = el("p", { class: "budget" },
    el("meter", { class: "bar inside", min: "0", max: String(b.limit), value: String(Math.min(b.spent, b.limit)), "aria-hidden": "true" }),
    el("span", { text: `${b.spent} of ${b.limit} Qloo calls used${b.saved ? `, ${b.saved} not spent` : ""}.` }));
  const lift = spentAll
    ? el("div", { class: "banner warn" },
      el("p", { text: `This outing has used all ${b.limit} of its Qloo calls. Only you can raise the limit, to at most ${state.data.callLimit.max}.` }),
      liftControl(out))
    : disclosure("lift", "Raise this outing's call limit", liftControl(out));
  $("#compare-body").replaceChildren(...parts, el("div", { class: "actions" }, ...buttons), budget, lift);
}

function compare(out, complete) {
  return run(async () => {
    setStatus("Asking Qloo: one search for the group, then one ranking per person.");
    const args = { outing_id: out.id };
    if (complete) args.complete = true;
    const result = await act(DISPATCH, "run_comparison", args);
    await refresh();
    const done = latest().comparison;
    setStatus(`${HEADLINES[done.outcome](done.foundCommon, sourceWord(latest()))} ${result.callsSpent} of ${result.callLimit} calls used.`);
    focusHeading("h-results");
  }, { watch: true });
}

/* ---- the call strip ---- */

const CALL_WORDS = { "/search": "search", "/v2/tags": "tags", "/v2/insights": "insights" };
const HOW_WORDS = { miss: ["live", "live"], cache: ["cached", "cache"], synthetic: ["sample", "sample"] };

function renderStrip() {
  const box = $("#strip");
  const calls = state.calls;
  if (!calls.length) {
    box.replaceChildren();
    return;
  }
  const count = (how) => calls.filter((c) => c.cache === how).length;
  const summary = `${calls.length} ${calls.length === 1 ? "call" : "calls"} in this workspace, oldest first: `
    + `${count("miss")} live to Qloo, ${count("cache")} answered from the cache, `
    + `${count("synthetic")} on sample data, which is not Qloo.`;
  box.replaceChildren(
    el("h3", { text: "The calls" }),
    el("p", { class: "facts-line", text: summary }),
    el("ol", { class: "strip", "aria-label": "Qloo calls, oldest first" }, calls.map((c) => {
      const [word, tone] = HOW_WORDS[c.cache] || [c.cache, "sample"];
      return el("li", { class: `chip ${tone}` },
        el("span", { class: "what", text: CALL_WORDS[c.path] || c.path }),
        el("span", { class: "how", text: word }));
    })));
}

/* ---- the board: a bar per person on every pick ---- */

function figureText(entry, member, view) {
  const band = entry.band ? `, ${view.synthetic ? "the sample's band" : BANDS} ${entry.band}` : "";
  return `${view.synthetic ? "sample affinity" : "affinity"} ${entry.affinity.toFixed(2)} on ${member.name}'s own scale${band}`;
}

function standingRow(entry, member, index, view) {
  const track = el("span", { class: "track", "aria-hidden": "true" },
    el("meter", { class: `bar ${entry.inUpperHalf ? "inside" : "outside"}`, min: "0", max: "1", value: String(entry.bar) }));
  track.style.setProperty("--half", `${view.line}%`);
  return el("li", {},
    el("span", { class: `disc hue-${index % 6}`, "aria-hidden": "true", text: initial(member.name) }),
    el("div", { class: "standing-body" },
      el("div", { class: "standing-line" },
        el("span", { class: "who", text: member.name }),
        el("span", { class: "rank", text: entry.ranked ? `ranks it ${entry.rank} of ${view.size}` : "Qloo gave no figure" }),
        entry.inUpperHalf ? null : el("span", { class: "outside", text: "outside their upper half" })),
      track,
      entry.ranked && entry.affinity != null ? el("span", { class: "figure", text: figureText(entry, member, view) }) : null,
      entry.restsOnOrganiserResolution
        ? el("span", { class: "by", text: `resolved by the organiser for ${member.name}` })
        : null));
}

function becauseList(place, out, view) {
  const favourites = Object.fromEntries(out.members.flatMap((m) => m.favourites.map((f) => [f.id, f])));
  const lines = place.perMember.filter((e) => e.because.length).map((e) => {
    const parts = e.because.map((b) => `“${favourites[b.favourite].name}” (${b.score.toFixed(2)})`);
    return el("li", { text: `${view.names[e.member]}: ${listOf(parts)}` });
  });
  if (!lines.length) {
    return el("p", { class: "hint", text: `${capital(view.who)} gave no explanation for this place, so no favourite is named.` });
  }
  return el("div", {},
    el("p", { class: "hint", text: `${view.synthetic ? "The sample data's" : "Qloo's"} explainability links this place to these favourites (scores from 0.1 up):` }),
    el("ul", { class: "because" }, lines));
}

function orderRule(place) {
  const by = { worst_rank: "the rank of the person it serves least", sum_of_ranks: "the sum of everyone's ranks", group_position: "Qloo's order for the group search" };
  return place.status === "common" && place.placedBy
    ? `Ordered by ${by[place.placedBy]}. That is this app's rule, not Qloo's.`
    : "Where it sits is this app's rule, not Qloo's: it counts who is outside the upper half.";
}

function pickControls(place, out, view) {
  if (out.chosen && out.chosen.placeId === place.entityId) {
    return el("p", { class: "picked", text: "Picked by you. Nothing is booked." });
  }
  const left = place.leftOut;
  const idle = view.unranked.filter((id) => !left.includes(id));
  const needs = [...left, ...idle];
  const ticked = state.acks.get(place.entityId) || new Set();
  state.acks.set(place.entityId, ticked);
  const button = el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": `pick:${place.entityId}`,
    onclick: () => run(async () => {
      const now = latest();
      const args = { outing_id: now.id, place_id: place.entityId, revision: now.revision };
      if (needs.length) args.acknowledge_left_out = needs;
      setStatus(`Picking ${place.name}`);
      await act(DISPATCH, "pick_place", args);
      await refresh();
      setStatus(`${place.name} is picked. Nothing is booked, sent or paid.`);
      focusHeading("h-decide");
    }),
  }, `Pick ${place.name}`);
  const boxes = needs.map((id) => {
    const box = el("input", { type: "checkbox", id: `ack-${place.entityId}-${id}` });
    box.checked = ticked.has(id);
    box.addEventListener("change", () => {
      if (box.checked) ticked.add(id);
      else ticked.delete(id);
    });
    const words = left.includes(id)
      ? `I know this place leaves out ${view.names[id]}.`
      : `I know ${view.names[id]} has not been ranked, so this place has no figure for them.`;
    return el("label", { class: "choice" }, box, el("span", { class: "choice-text", text: words }));
  });
  const ready = () => !view.stale && needs.every((id) => ticked.has(id));
  const note = view.stale ? el("p", { class: "hint", text: "The comparison is out of date. Compare again before picking." }) : null;
  bindReady(button, ready, boxes.map((label) => label.querySelector("input")));
  return el("div", { class: "pick" },
    needs.length
      ? el("fieldset", { class: "favourite" }, el("legend", { text: "To pick this place, say who it leaves out" }), ...boxes)
      : null,
    note,
    el("div", { class: "actions" }, button));
}

function ruleOutControls(place, out) {
  const id = `reason-${place.entityId}`;
  const input = remember(`reason:${place.entityId}`, el("input", {
    id, type: "text", maxlength: "200", autocomplete: "off", "data-focus": `reason:${place.entityId}`,
  }));
  const button = el("button", {
    type: "button",
    "data-needs-person": true,
    "data-focus": `rule-out:${place.entityId}`,
    onclick: () => run(async () => {
      const now = latest();
      await act(DISPATCH, "rule_out_place", { outing_id: now.id, place_id: place.entityId, reason: input.value.trim() });
      state.fields.delete(`reason:${place.entityId}`);
      await refresh();
      setStatus(`${place.name} is ruled out. It stays under also ranked, with your reason.`);
      focusHeading("h-results");
    }),
  }, "Rule this place out");
  bindReady(button, () => input.value.trim().length > 0, [input]);
  enterPresses(input, button);
  return disclosure(`rule:${place.entityId}`, "Rule this place out",
    el("div", { class: "field" }, el("label", { for: id, text: "Why? The reason stays with the place." }), input),
    el("div", { class: "actions" }, button));
}

function placeCard(place, out, view) {
  const picked = out.chosen && out.chosen.placeId === place.entityId;
  const verdict = place.status === "common"
    ? "In the upper half of every ranked person's own ranking."
    : `Leaves out ${listOf(place.leftOut.map((id) => view.names[id]))}.`;
  const site = safeUrl(place.website);
  const where = [place.address, place.tags.length ? place.tags.join(", ") : null].filter(Boolean).join(" · ");
  const origin = view.synthetic ? "invented sample data" : "from Qloo";
  return el("article", { class: `place${view.stale ? " out-of-date" : ""}${picked ? " is-picked" : ""}` },
    el("div", { class: "card-head" },
      el("h5", { text: place.name }),
      view.synthetic ? el("span", { class: "stamp draft", text: "Sample data" }) : null,
      picked ? el("span", { class: "stamp done", text: "Picked" }) : null),
    el("p", { class: "verdict", text: verdict }),
    where || site ? el("p", { class: "where" }, where ? `${where} (${origin})` : "",
      site ? [" ", el("a", { href: site, rel: "noopener noreferrer", target: "_blank", text: view.synthetic ? "Website (invented)" : "Website, as Qloo lists it" })] : null) : null,
    el("ul", { class: "standing" }, place.perMember.map((entry) => standingRow(
      entry, out.members.find((m) => m.id === entry.member), view.order[entry.member], view))),
    disclosure(`why:${place.entityId}`, "Why this place",
      becauseList(place, out, view),
      el("p", { class: "hint", text: orderRule(place) }),
      el("p", { class: "hint", text: `${SENTENCES.notComparable} ${SENTENCES.notAPrediction}` })),
    pickControls(place, out, view),
    ruleOutControls(place, out));
}

function alsoRanked(out, others, view) {
  const rows = others.map((place) => {
    const ranks = place.perMember.map((e) => `${view.names[e.member]} ${e.ranked ? e.rank : "–"}`).join(" · ");
    const kind = place.status === "ruled_out"
      ? `ruled out: ${place.ruledOut.reason}`
      : place.status === "common" ? "common, below the five shown" : place.status.replace(/_/g, " ");
    const undo = place.status === "ruled_out"
      ? el("button", {
        type: "button",
        class: "quiet",
        "data-needs-person": true,
        "data-focus": `undo:${place.entityId}`,
        onclick: () => run(async () => {
          const now = latest();
          await act(DISPATCH, "rule_out_place", { outing_id: now.id, place_id: place.entityId, undo: true });
          await refresh();
          setStatus(`${place.name} is back on the board.`);
        }),
      }, `Put ${place.name} back`)
      : null;
    return el("li", {}, el("strong", { text: place.name }), ` (${kind}): ${ranks}`, undo);
  });
  return disclosure("also", `Also ranked (${others.length})`, el("ul", { class: "also" }, rows));
}

function groupTitle(text) {
  return el("h4", { text });
}

function renderResults(out) {
  const box = $("#results");
  const c = out.comparison;
  if (!c) {
    box.replaceChildren();
    return;
  }
  const names = Object.fromEntries(out.members.map((m) => [m.id, m.name]));
  const size = out.longList ? out.longList.size : 0;
  const half = Math.ceil(size / 2);
  const view = {
    stale: c.stale,
    size,
    names,
    order: Object.fromEntries(out.members.map((m, i) => [m.id, i])),
    line: size ? ((size - half + 1) / size) * 100 : 50,
    unranked: c.unrankedMembers,
    synthetic: out.source === "synthetic",
    who: sourceWord(out),
  };
  const active = out.places.filter((p) => p.status !== "ruled_out");
  const common = active.filter((p) => p.status === "common");
  const near = active.filter((p) => p.status === "near");
  const shown = common.slice(0, PICKS_SHOWN);
  const others = [
    ...out.places.filter((p) => p.status === "ruled_out"),
    ...out.places.filter((p) => !shown.includes(p) && !near.includes(p) && p.status !== "ruled_out"),
  ];
  const nodes = [el("h3", { id: "h-results", tabindex: "-1", text: "Result" })];
  if (c.stale) {
    nodes.push(banner("warn", "The matches or conditions changed after this comparison, so it is out of date. Compare again."));
  }
  if (!c.stale && c.unrankedMembers.length && c.outcome === "common") {
    nodes.push(banner("warn", `This comparison is incomplete: ${listOf(c.unrankedMembers.map((id) => names[id]))} ${c.unrankedMembers.length === 1 ? "has" : "have"} not been ranked yet, so a place shown here as common may still leave them out. Compare again to rank them.`));
  }
  nodes.push(el("p", { class: `verdict${c.outcome === "common" ? "" : " none"}`, text: HEADLINES[c.outcome](c.foundCommon, view.who) }));
  const facts = [`Calls: ${out.budget.spent} of ${out.budget.limit} used${out.budget.saved ? `, ${out.budget.saved} not spent` : ""}.`];
  if (c.stoppedBecause && STOPS[c.stoppedBecause]) facts.push(STOPS[c.stoppedBecause]);
  if (c.chance) facts.push(sentence(c.chance));
  for (const [id, got] of Object.entries(c.partial)) {
    facts.push(`${capital(view.who)} ranked only ${got.ranked} of ${got.of} places for ${names[id]}.`);
  }
  if (c.unrankedMembers.length) facts.push(`Not ranked: ${listOf(c.unrankedMembers.map((id) => names[id]))}.`);
  const figures = out.places.some((p) => p.perMember.some((e) => e.ranked && e.affinity != null));
  if (c.rankedMembers.length && !figures) facts.push(`${capital(view.who)} returned an order without affinity figures, so none is shown.`);
  nodes.push(el("p", { class: "facts-line", text: facts.join(" ") }));
  if (shown.length || near.length) {
    nodes.push(el("p", { class: "legend", text: `Each bar is one person's own ranking of the ${size} places: the longer the bar, the higher ${view.who} ranks the place for that person's favourites. The tick marks the half-way line, this app's rule for the upper half. ${SENTENCES.notComparable}` }));
  }
  if (shown.length) {
    nodes.push(groupTitle(common.length > shown.length ? `Common places (${shown.length} of ${common.length})` : "Common places"),
      el("div", { class: "places" }, shown.map((p) => placeCard(p, out, view))));
  }
  if (near.length) {
    nodes.push(groupTitle(c.outcome === "common" ? "Near places: each leaves someone out" : "Closest places: each leaves someone out"),
      el("div", { class: "places" }, near.map((p) => placeCard(p, out, view))));
  }
  if (c.outcome === "thin_list" && out.places.length) {
    nodes.push(el("p", { class: "facts-line", text: `Places ${view.who} returned, not ranked:` }),
      el("ul", {}, out.places.map((p) => el("li", { text: p.name }))));
  } else if (others.length) {
    nodes.push(alsoRanked(out, others, view));
  }
  nodes.push(renderTrace(out));
  box.replaceChildren(...nodes);
}

function renderTrace(out) {
  const names = Object.fromEntries(out.members.map((m) => [m.id, m.name]));
  const items = out.trace.map((entry) => {
    const call = entry.request ? `${entry.request.path}, ${entry.cache}` : "no call";
    const refused = entry.outcome === "ok" ? "" : ` Refused: ${entry.outcome}.`;
    const who = entry.member ? `${names[entry.member]}: ` : "";
    return el("li", { text: `${entry.tool} (${entry.actor}): ${who}${entry.because} (${call}; ${entry.callsSpent} of ${out.budget.limit}).${refused}` });
  });
  return disclosure("trace", `What the agent did (${items.length} steps)`,
    el("ol", { class: "trace", "aria-live": "polite" }, items));
}

/* ---- pick, draft and sign off ---- */

function draftTitle(out, draft) {
  const place = out.places.find((p) => p.entityId === draft.placeId);
  const what = draft.kind === "invitation" ? "Invitation to the group" : "Booking request to the place";
  return place ? `${what}: ${place.name}` : what;
}

function mailLink(out, draft) {
  const subject = draft.kind === "invitation" ? out.label : `Enquiry for ${out.members.length} people`;
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(draft.text)}`;
}

function unnamedFavourites(out) {
  return out.members
    .filter((m) => m.favourites.some((f) => f.resolved && f.resolvedBy === "organiser_for"))
    .map((m) => m.name);
}

function draftCard(out, draft) {
  const released = draft.state === "released";
  const headId = `h-draft-${draft.draftId}`;
  const text = el("textarea", {
    id: `msg-${draft.draftId}`, readonly: true, rows: String(draft.text.split("\n").length + 2),
    "aria-labelledby": headId,
  }, draft.text);
  const card = el("article", { class: `draft${released ? " released" : ""}` },
    el("div", { class: "draft-head" },
      el("h4", { id: headId, text: draftTitle(out, draft) }),
      el("span", { class: `stamp ${released ? "done" : "draft"}`, text: released ? `Signed off by ${draft.signedOffBy}` : "DRAFT" })),
    text);
  const hidden = draft.kind === "invitation" ? unnamedFavourites(out) : [];
  if (hidden.length) {
    card.append(el("p", { class: "hint", text: `It names no favourite for ${listOf(hidden)}, because the organiser matched those for them. A favourite is named only where the person matched it themself.` }));
  }
  if (released) {
    const note = el("p", { class: "copy-note", id: `copy-${draft.draftId}-note`, role: "status" });
    card.append(
      el("div", { class: "actions" },
        el("button", { type: "button", class: "primary", "data-focus": `copy:${draft.draftId}`, onclick: () => copyField(text, note) }, "Copy the message"),
        el("a", { class: "button-link", href: mailLink(out, draft), text: "Open in your mail app" }),
        el("a", { class: "button-link", href: `/api/message/${out.id}-${draft.draftId}.txt`, target: "_blank", rel: "noopener", text: "Plain text" })),
      note,
      el("p", { class: "hint", text: `No recipient is filled in. ${SENTENCES.sendsNothing}` }));
    return card;
  }
  const id = `sender-${draft.draftId}`;
  const input = remember(id, el("input", {
    id, type: "text", maxlength: "60", autocomplete: "off", "aria-describedby": `${id}-hint`, "data-focus": id,
  }));
  const button = el("button", {
    type: "button",
    class: "primary",
    "data-needs-person": true,
    "data-focus": `sign:${draft.draftId}`,
    onclick: () => run(async () => {
      const now = latest();
      await act(DISPATCH, "sign_off_message", {
        outing_id: now.id, draft_id: draft.draftId, sender_name: input.value.trim(), revision: now.revision,
      });
      state.fields.delete(id);
      await refresh();
      setStatus("The message is signed off. It is text to copy: nothing was sent.");
      if (!focusKey(`copy:${draft.draftId}`)) focusHeading("h-decide");
    }),
  }, "Sign off");
  bindReady(button, () => input.value.trim().length > 0, [input]);
  enterPresses(input, button);
  card.append(
    el("div", { class: "field" },
      el("label", { for: id, text: "Sender: your name, as it will read at the end" }),
      el("p", { class: "hint", id: `${id}-hint`, text: `Signing off removes the DRAFT line. ${SENTENCES.sendsNothing}` }),
      el("div", { class: "copy-line" }, input, button)));
  return card;
}

function renderDecide(out) {
  const section = $("#decide");
  const chosen = out.chosen;
  section.hidden = !chosen && !out.drafts.length;
  if (section.hidden) return;
  const stale = out.comparison && out.comparison.stale;
  const parts = [];
  if (chosen) {
    const named = (ids) => listOf(ids.map((id) => out.members.find((m) => m.id === id).name));
    parts.push(el("p", { class: "verdict", text: `You picked ${chosen.name}.` }));
    if (chosen.leftOut.length) {
      parts.push(el("p", { class: "provenance", text: `It leaves out ${named(chosen.leftOut)}, and you said you know.` }));
    }
    if (chosen.unranked.length) {
      parts.push(el("p", { class: "provenance", text: `${capital(named(chosen.unranked))} had not been ranked when you picked, and you said you know.` }));
    }
    if (stale) {
      parts.push(banner("warn", "The conditions or matches changed after this pick, so it rests on an older comparison. Compare again before drafting."));
    }
    const ask = (kind, words) => el("button", {
      type: "button",
      "data-focus": `draft:${kind}`,
      "data-not-ready": Boolean(stale),
      onclick: () => run(async () => {
        const now = latest();
        setStatus(`Writing the ${words}`);
        const made = await act(DISPATCH, "write_draft", { outing_id: now.id, place_id: now.chosen.placeId, kind });
        await refresh();
        setStatus(`The ${words} is a DRAFT. Name the sender and sign it off to release it.`);
        if (!focusKey(`sender-${made.draftId}`)) focusHeading("h-decide");
      }),
    }, `Draft the ${words}`);
    parts.push(el("div", { class: "actions" }, ask("invitation", "invitation"), ask("booking_request", "booking request")));
  }
  parts.push(el("p", { class: "hint", text: SENTENCES.sendsNothing }));
  parts.push(...out.drafts.map((d) => draftCard(out, d)));
  $("#decide-body").replaceChildren(...parts);
  for (const area of document.querySelectorAll("#decide-body textarea")) area.style.height = `${area.scrollHeight + 2}px`;
}

/* ---- the agent address and the agent console ---- */

function renderAgent(data, out) {
  const section = $("#agent");
  section.hidden = false;
  const address = data.agentAddress;
  $("#agent-body").replaceChildren(...(address ? [
    copyRow("agent-address", "Agent address", address),
    copyRow("agent-mcp", "MCP endpoint (revisions 2026-07-28, 2025-11-25 and 2025-06-18)", `${address}/mcp`),
    copyRow("agent-claude", "Add it to Claude Code", `claude mcp add --transport http common-ground ${address}/mcp`),
    el("p", { class: "hint", text: "A script can also GET the tools at the agent address plus /tools and POST {\"tool\": …, \"args\": …} to it plus /dispatch." }),
  ] : [
    el("p", { class: "hint", text: "The agent address is shown only to requests the browser labels as yours, so it is not shown here." }),
  ]));
  renderConsole(out);
}

function skeleton(name, out) {
  const spec = state.tools.find((t) => t.name === name);
  const place = out.places.find((p) => p.status === "common");
  const guess = {
    outing_id: out.id,
    member_id: out.members[0].id,
    favourite_id: "f1",
    place_id: place ? place.entityId : "",
    query: "restaurant",
    kind: "invitation",
    revision: out.revision,
  };
  const keys = spec ? spec.inputSchema.required : ["outing_id", "place_id", "revision"];
  return JSON.stringify(Object.fromEntries(keys.map((k) => [k, guess[k] ?? ""])), null, 2);
}

function describeReply(reply) {
  if (!reply.json) return { line: `The server answered ${reply.status} with no readable body.`, text: "" };
  const j = reply.json;
  const line = j.ok ? `ok: ${j.outcome}` : `${j.outcome}: ${say(new Problem(j.outcome, j.error && j.error.detail))}`;
  return { line, text: JSON.stringify(j, null, 2) };
}

function renderConsole(out) {
  const body = $("#console-body");
  const tool = remember("console:tool", el("input", {
    id: "console-tool", type: "text", list: "console-tools", autocomplete: "off", spellcheck: "false", "data-focus": "console:tool",
  }));
  const args = remember("console:args", el("textarea", {
    id: "console-args", rows: "5", spellcheck: "false", "data-focus": "console:args",
  }));
  if (!state.fields.has("console:tool")) tool.value = state.console.tool;
  if (!state.fields.has("console:args")) args.value = state.console.args;
  const status = el("p", { class: "copy-note", id: "console-status", role: "status", text: state.console.status });
  const output = el("pre", { class: "console-out", id: "console-out", tabindex: "0", "aria-label": "Full answer of the last run", text: state.console.output });
  const send = (name, text) => run(async () => {
    state.console.tool = name;
    state.console.args = text;
    state.fields.set("console:tool", name);
    state.fields.set("console:args", text);
    tool.value = name;
    args.value = text;
    let parsed;
    try {
      parsed = JSON.parse(text.trim() || "{}");
    } catch {
      state.console.status = "The arguments are not valid JSON, so nothing was sent.";
      state.console.output = "";
      status.textContent = state.console.status;
      output.textContent = "";
      return;
    }
    setStatus(`Running ${name || "(no name)"} as the agent`);
    const reply = await request("POST", DISPATCH, { tool: name, args: parsed }, AS_AGENT);
    const said = describeReply(reply);
    state.console.status = `Sent as the agent. ${said.line}`;
    state.console.output = said.text;
    status.textContent = state.console.status;
    output.textContent = said.text;
    setStatus(state.console.status);
    await refresh();
  });
  const run_ = el("button", {
    type: "button",
    class: "primary",
    "data-focus": "console:run",
    onclick: () => send(tool.value.trim(), args.value),
  }, "Run as the agent");
  const pick = el("button", {
    type: "button",
    "data-focus": "console:pick",
    onclick: () => send("pick_place", skeleton("pick_place", latest())),
  }, "Ask the agent to pick a place");
  const fill = el("button", {
    type: "button",
    class: "quiet",
    "data-focus": "console:fill",
    onclick: () => {
      const text = skeleton(tool.value.trim(), latest());
      args.value = text;
      state.fields.set("console:args", text);
    },
  }, "Fill in the arguments");
  body.replaceChildren(
    el("datalist", { id: "console-tools" }, state.tools.map((t) => el("option", { value: t.name }))),
    el("div", { class: "field" }, el("label", { for: "console-tool", text: "Tool name" }), tool),
    el("div", { class: "field" }, el("label", { for: "console-args", text: "Arguments, as JSON" }), args),
    el("div", { class: "actions" }, run_, fill, pick),
    status,
    output);
}

/* ---- the organiser's page ---- */

function renderOrganiser() {
  const data = state.data;
  state.gate = gateBroken(data);
  const out = latest();
  const planning = !out || state.planning;
  renderBanners(data, planning ? null : out);
  $("#describe").hidden = !planning;
  for (const id of ["summary", "match", "kind", "compare"]) $(`#${id}`).hidden = planning;
  if (planning) {
    $("#agent").hidden = true;
    $("#decide").hidden = true;
  } else {
    const keep = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute("data-focus");
    renderSummary(out);
    renderConditions(out);
    renderMatch(out, data);
    renderKind(out);
    renderCompare(out);
    renderStrip();
    renderResults(out);
    renderDecide(out);
    renderAgent(data, out);
    syncButtons();
    if (keep) focusKey(keep);
  }
  syncButtons();
}

async function organiserExtras() {
  state.calls = (await load("/api/calls")).calls;
  if (!state.tools.length) state.tools = (await load("/api/tools")).tools;
}

async function searchOne(member, favourite) {
  const out = latest();
  await run(async () => {
    setStatus(`Asking Qloo what “${favourite.name}” could mean`);
    await act(DISPATCH, "look_up_favourite", { outing_id: out.id, member_id: member.id, favourite_id: favourite.id });
    await refresh();
  });
}

/* ---- the form ---- */

let personCount = 0;

function peopleRows() {
  return [...document.querySelectorAll("#people .person-fields")];
}

function renumber() {
  const rows = peopleRows();
  rows.forEach((row, index) => {
    row.querySelector(".legend-text").textContent = `Person ${index + 1}`;
    row.querySelector(".role-note").textContent = index === 0 ? "(the organiser)" : "";
    const disc = row.querySelector(".disc");
    disc.className = `disc hue-${index % 6}`;
    disc.textContent = initial(row.querySelector(".p-name").value);
    row.querySelector(".remove-person").hidden = rows.length <= MIN_PEOPLE;
  });
  $("#add-person").toggleAttribute("data-not-ready", rows.length >= MAX_PEOPLE);
  syncButtons();
}

function addPerson(values) {
  personCount += 1;
  const row = $("#person-template").content.firstElementChild.cloneNode(true);
  const hint = row.querySelector(".hint");
  hint.id = `hint-${personCount}`;
  row.querySelectorAll(".field").forEach((field, i) => {
    const input = field.querySelector("input");
    input.id = `p${personCount}-${i}`;
    field.querySelector("label").htmlFor = input.id;
    if (i > 0) input.setAttribute("aria-describedby", hint.id);
  });
  const name = row.querySelector(".p-name");
  const favourites = row.querySelectorAll(".p-fav");
  if (values) {
    name.value = values.name;
    values.favourites.forEach((text, i) => { if (favourites[i]) favourites[i].value = text; });
  }
  name.addEventListener("input", renumber);
  row.querySelector(".remove-person").addEventListener("click", () => {
    row.remove();
    renumber();
    $("#add-person").focus();
  });
  $("#people").append(row);
  renumber();
  return row;
}

function readForm() {
  const text = (id) => $(id).value.trim();
  const level = (id) => (text(id) ? Number(text(id)) : null);
  return {
    label: text("#f-label"),
    when: text("#f-when") || null,
    place_text: text("#f-city"),
    day: $("#f-day").value,
    price_min: level("#f-min"),
    price_max: level("#f-max"),
    kind_query: text("#f-kind") || null,
    members: peopleRows().map((row) => ({
      name: row.querySelector(".p-name").value.trim(),
      favourites: [...row.querySelectorAll(".p-fav")].map((i) => i.value.trim()).filter(Boolean),
    })),
  };
}

function fill(args) {
  $("#f-label").value = args.label || "";
  $("#f-when").value = args.when || "";
  $("#f-city").value = args.place_text || "";
  $("#f-day").value = args.day;
  $("#f-min").value = args.price_min == null ? "" : String(args.price_min);
  $("#f-max").value = args.price_max == null ? "" : String(args.price_max);
  $("#f-kind").value = args.kind_query || "";
  peopleRows().forEach((row) => row.remove());
  args.members.forEach((member) => addPerson(member));
}

function start(args) {
  return run(async () => {
    setStatus("Opening the outing");
    await act(DISPATCH, "open_outing", args);
    state.planning = false;
    for (const store of [state.choices, state.fields, state.acks, state.open]) store.clear();
    state.kindChoice = undefined;
    state.console = { tool: "", args: "", status: "", output: "" };
    await refresh();
    const out = latest();
    const pairs = out.members.flatMap((m) => m.favourites.map((f) => [m, f]));
    for (const [i, [member, favourite]] of pairs.entries()) {
      setStatus(`Asking Qloo what “${favourite.name}” could mean (${i + 1} of ${pairs.length})`);
      await act(DISPATCH, "look_up_favourite", { outing_id: out.id, member_id: member.id, favourite_id: favourite.id });
    }
    if (args.kind_query) {
      setStatus(`Asking Qloo for kinds of place matching “${args.kind_query}”`);
      await act(DISPATCH, "look_up_kind", { outing_id: out.id, query: args.kind_query });
    }
    await refresh();
    setStatus("Qloo has proposed matches. Say which one each person meant.");
    focusHeading("h-match");
  });
}

async function sample() {
  const reply = await request("GET", "/api/sample");
  if (reply.status !== 200 || !reply.json) {
    showProblem(new Problem("unreachable"));
    return;
  }
  fill(reply.json.args);
  await start(reply.json.args);
}

function organiserPage() {
  page = { statePath: "/api/state", render: renderOrganiser, moveOn: moveOnFrom, extra: organiserExtras, top: "h-match" };
  addPerson();
  addPerson();
  $("#add-person").addEventListener("click", () => {
    addPerson().querySelector(".p-name").focus();
  });
  $("#outing-form").addEventListener("submit", (event) => {
    event.preventDefault();
    start(readForm());
  });
  $("#sample").addEventListener("click", sample);
  $("#again").addEventListener("click", () => {
    state.planning = true;
    renderOrganiser();
    focusHeading("h-describe");
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !state.busy && state.data && latest() && !state.planning) {
      refresh().catch(() => {});
    }
  });
  return init();
}

/* ---- a member's own page ---- */

function renderMember() {
  const data = state.data;
  state.gate = gateBroken(data);
  renderBanners(data, data.outing);
  const member = data.member;
  const outingId = data.outing.id;
  const path = `${page.base}/dispatch`;
  const keep = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute("data-focus");
  $("#mine").replaceChildren(
    el("p", { class: "provenance", text: `Outing: ${data.outing.label}${data.outing.when ? `, ${data.outing.when}` : ""}.` }),
    el("div", { class: "person" },
      personHead(member, 0, ""),
      ...member.favourites.map((f) => favouriteBlock(member, f, false)),
      member.favourites.length
        ? resolveButton(member, member.favourites, path, outingId)
        : el("p", { class: "empty", text: "The organiser has not added any favourites for you yet. You can add one below." }),
      addFavouriteBox(member, outingId, path, "Add a favourite of your own", false)));
  syncButtons();
  if (keep) focusKey(keep);
}

function memberPage() {
  const token = location.pathname.split("/")[2];
  page = {
    statePath: `/api/member/${token}/state`,
    base: `/api/member/${token}`,
    render: renderMember,
    moveOn: () => focusHeading("h-mine"),
    top: "h-mine",
  };
  return init();
}

async function init() {
  try {
    state.data = await load(page.statePath);
    if (page.extra) await page.extra();
    page.render();
  } catch (error) {
    renderBanners(null, null);
    showProblem(error instanceof Problem ? error : new Problem("unreachable"));
  }
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.body.dataset.page === "member") memberPage();
  else organiserPage();
});
