# Putting Common Ground on a host that speaks HTTPS

A browser labels its requests (`Sec-Fetch-Site`) only when the page came over HTTPS, or from `localhost`. Common Ground
uses that label to tell a person's click from an agent's call, so on plain HTTP no Resolve, Pick or Sign off button
could ever count as a person's. A hosted copy must therefore be reached over HTTPS, and this guide gives two ways to
get there. Each is one sitting with a person at the keyboard, who pastes the Qloo key where one is needed and clicks
the button that creates the resource. When an assistant drives the console (here, Claude Code in the owner's browser),
it fills in every field, leaves the key empty and stops; the owner checks each field, pastes the key and clicks the
create button personally. **If a card, phone or ID screen appears at any step, stop and tell whoever is driving.
Neither host needs one.**

| | Render, a free web service | EC2, with Caddy in front |
|---|---|---|
| Reach for it | first | if Render refuses the account, suspends the service, or wakes too slowly |
| HTTPS comes from | Render, at `<name>.onrender.com` | Caddy, at `<public IPv4 with dashes>.nip.io` |
| Asleep when idle | yes: after 15 minutes without inbound traffic, awake again in about a minute | never |
| A workspace survives | until the next sleep, restart or deploy | until the service restarts |
| The key is entered | as an environment variable on the creation form | on one marked line of a boot script |
| Changing mode or key later | edit the variable, save, redeploy | not possible without a login: launch a fresh instance |

All pages this guide leans on were read on 21 Oct 2026 and are listed at the end. What could not be checked without an
account is gathered under "What no one could check without an account", and the first sitting settles it.

## Choose sample or live first

One server serves one source for its whole life, set by `COMMON_GROUND_PROVIDER`.

| Value | What the hosted copy does | Needs a key |
|---|---|---|
| `fake` | Serves the sample source: invented places, the banner "Synthetic sample data. Qloo is not being called." on every page, a "Sample data" stamp on every card. The whole flow works. | No |
| `live` | Calls Qloo from the server. Until the key-day probe has run and its block has been pasted into `common_ground/measured.py`, every live call is refused with `shapes_unverified`, and the page says "Live mode is on, but Qloo's response shapes have not been checked yet, so no live call runs." | Yes |

**Until the probe has run, deploy with `fake`.** A live server that refuses every call is not a demo. Once the probe
has passed, publish the updated code and switch to `live`. The banner names the mode on every page, so nothing a
visitor sees claims more than it is. With `fake`, the key is not needed at the sitting and should not be pasted.

## Settings both hosts use

The server reads these from the environment; `.env.example` lists every name, all empty.

| Setting | What it does here |
|---|---|
| `COMMON_GROUND_PROVIDER` | `fake` or `live`, above. With `live` and no key the server will not start and the log says `key: missing`, so a forgotten key shows up at the sitting instead of in front of a visitor |
| `QLOO_API_KEY` | your own hackathon key, the only secret; typed by you and never by an assistant; only with `live` |
| `COMMON_GROUND_BIND` | `0.0.0.0` where the host's proxy reaches the server over a private network (Render); `127.0.0.1` where Caddy runs on the same machine |
| `PORT` or `COMMON_GROUND_PORT` | the port to listen on; `PORT` wins when both are set; with neither it is 8761 |
| `COMMON_GROUND_ALLOWED_HOSTS` | the public host name, no port. On Render it stays empty, because `RENDER_EXTERNAL_HOSTNAME` is read instead |
| `COMMON_GROUND_TRUST_PROXY` | `1` when a proxy is in front, so the client address is the right-most `X-Forwarded-For` value |
| `COMMON_GROUND_DAILY_LIVE_CALLS` | how many live Qloo calls the server may make in a run (default 300); lower it if the key's email states a smaller quota. It has no effect on `fake` |

A bind beyond loopback with no allowed host makes the server refuse to start, so it can never answer every `Host`. It
writes no per-request log. `GET /healthz` answers `ok` for any `Host`, takes no cookie and reveals no state.

## Host one: a free Render web service

### Every field of the creation form

In the Render dashboard choose **New**, **Web Service**, then the **Git Provider** tab. Connecting GitHub is an OAuth
grant only you can give; offer just the `common-ground` repository. (The **Public Git Repository** tab cannot
auto-deploy, so it suits a throwaway test only.) Labels follow Render's own pages; leave anything not listed at its
default.

| Field | Value |
|---|---|
| Repository | `guptachetan1995/common-ground` |
| Name | `common-ground` (the address becomes `https://common-ground.onrender.com`, or carries a suffix if the name is taken; the service page shows the real one) |
| Language | `Python 3` |
| Branch | `main` |
| Region | `Oregon`, the default; a region cannot be changed once the service exists |
| Root Directory | empty |
| Build Command | `true` |
| Start Command | `python -m common_ground serve` |
| Compute plan | `Free` |
| Health Check Path (under Advanced) | `/healthz` |
| Auto-Deploy (Settings page) | `On Commit`, the default, so a publish redeploys; set it to `Off` after the Devpost Submit to freeze the demo |

Environment Variables, under Advanced, one row each:

| Key | Value |
|---|---|
| `COMMON_GROUND_PROVIDER` | `fake` until the probe has run, then `live` |
| `QLOO_API_KEY` | you paste it, and only with `live`. Whoever drives the form adds the key's name only when `live` is chosen and leaves the value empty |
| `COMMON_GROUND_BIND` | `0.0.0.0` |
| `PORT` | `10000` |
| `COMMON_GROUND_TRUST_PROXY` | `1` |
| `COMMON_GROUND_DAILY_LIVE_CALLS` | `300` |

Left unset deliberately: `COMMON_GROUND_ALLOWED_HOSTS` (the server reads Render's `RENDER_EXTERNAL_HOSTNAME`, the
service's own `onrender.com` name, so nobody has to guess the final name before the create click),
`COMMON_GROUND_PORT` and `PYTHON_VERSION`.

Reasons for the less obvious values:

- **Python.** The app needs 3.11 or newer. `.python-version` at the repository root reads `3.13` and Render honours it,
  taking the latest patch of a version written without one; a `PYTHON_VERSION` variable would override it, so none is
  set. A service created today and given no version gets 3.14.8, which also runs the app. The deploy log names the
  version in use.
- **Build Command `true`.** There is nothing to install, because the app uses only the standard library. Render
  requires a build command for a non-Docker service, and its Blueprint reference writes `buildCommand: 'true'` for a
  case that builds nothing.
- **`python`, not `python3`.** Every start command on Render's pages says `python`. If the log reports `python: command
  not found`, change the Start Command to `python3 -m common_ground serve`.
- **`PORT=10000`.** Render says every web service defaults to 10000 and binds the port in `PORT`. Writing it down makes
  the port visible on the Environment page, and the server reads `PORT` before its own setting.
- **Free.** The plan is 0.1 CPU and 512 MB, which a standard-library server capped at 64 handler threads does not
  strain.
- **No Blueprint file.** Render's reference gives a Blueprint service the paid plan `0.5c-512mb` unless `plan: free` is
  written, so none is committed; the form above is the whole recipe.

### The sitting, as it unfolds (about 20 minutes)

1. Sign in to Render. A card, phone or ID screen: stop and say so.
2. The assistant fills in the form and says what it filled, including that the key is empty or absent.
3. You compare each field with the two tables. With `live`, you paste the key into the value of `QLOO_API_KEY` yourself.
   Then you click **Create Web Service**.
4. On the Deploys page Render clones the repository, runs `true`, starts the program and sends health checks, and shows
   **Live** once they pass; expect one to three minutes (an estimate). Failing checks for 15 minutes end in a cancelled
   deploy. The log then reads `Common Ground is listening on 0.0.0.0:10000; reach it through the host's HTTPS address,
   because the person gate needs HTTPS`, followed by the mode line: `Synthetic sample data. Qloo is not being called.`
   for `fake`, or `Live: Qloo is being called (key: set)` and, until the probe, `Live calls are refused until the
   key-day probe has checked Qloo's response shapes (shapes_unverified).`
5. Open the service's `onrender.com` address in a private window and run the checks further down.

### How a free service behaves

- With no inbound traffic for 15 minutes Render stops it. The next visit meets Render's own loading page for about a
  minute and then an empty app: every workspace, personal link and agent address from before is gone, and a tab left
  open says "This workspace is gone".
- Render sends health checks every few seconds. Its pages do not say whether those count as traffic, so whether the
  service ever sleeps is read from the first walk, not assumed.
- The disk is ephemeral, which changes nothing: the app keeps everything in memory and writes no file.
- Render may restart a free service at any moment. The 750 free hours a month belong to the **workspace** and are shared
  by all its free services. One service awake all month uses 744 of them, so two such services would need 1,488 and
  Render would suspend both until the next month. For that reason neither is ever pinged awake.

## Host two: one EC2 instance, with Caddy in front

### Every field of the launch wizard

Open EC2 in a region your account allows (an organisation policy can block some; Sydney, `ap-southeast-2`, worked for
the author's account). Labels follow the console.

Fill the wizard from top to bottom:

1. **Name and tags:** `common-ground`.
2. **Application and OS Images:** the `Amazon Linux 2023 AMI`, `64-bit (x86)`.
3. **Instance type:** `t3.micro`.
4. **Key pair (login):** `Proceed without a key pair (not recommended)`.
5. **Network settings:** the default VPC, with Auto-assign public IP set to `Enable`. In the firewall box create a new
   security group, `common-ground-sg`, that allows `HTTP` (80) and `HTTPS` (443) from `0.0.0.0/0`, and delete the SSH rule.
6. **Configure storage:** leave the default 8 GiB `gp3`.
7. **Advanced details:** Metadata version `V2 only (token required)`; in User data, paste the whole of
   `deploy/ec2/user-data.sh` as text.
8. **Summary panel:** Number of instances `1`, then check everything once more before **Launch instance**.

Port 80 serves the certificate's HTTP challenge and the redirect to HTTPS; port 443 is the site. With no SSH and no key
pair nothing on the instance can be changed afterwards, so a typo or a wrong key means launching again, which brings a
new address and a new certificate. Switching the provider from `fake` to `live` is the same thing: a new launch of
about 20 minutes, after which the old instance is terminated.

### The key line and the provider line

Two lines at the top of the script can change:

```
QLOO_API_KEY=            # <<< the one line to edit: with PROVIDER=live, type the Qloo key straight after the =
PROVIDER=fake            # fake: the sample source, no key, and the page says so. live: calls Qloo, needs the key
```

The driver pastes the script as committed (`fake`, empty key), or with `PROVIDER=live` and the key line still empty,
and says which. For `live`, you click into the text box, put the cursor straight after the `=` of the key line, and type
the key with no quotes and no spaces. The assistant takes no screenshot while the key is in the box. A `live` script
with an empty key line stops before it installs anything and says why in the instance's system log; a key holding a
space, a quote or a backslash is refused the same way.

A typed key travels with the script. AWS stores the script as pasted under `/var/lib/cloud/instances/<id>/`, anyone
signed in to the account can read it by opening the instance's user data, and any process on the instance can read it
from the metadata service. Separately, the script writes the key to `/etc/common-ground.env`, readable by root alone,
for the service to load. The key itself is free and personal.

### The sitting, as it unfolds (about 20 minutes)

1. Open the AWS console, signing in again yourself if the session lapsed. A card, phone or ID screen: stop and say so.
2. The assistant opens EC2 and fills in the wizard. You check each field against the list above.
3. With `live`, you type the key into the marked line. You read the Summary panel and click **Launch instance**.
4. After about three to five minutes (an estimate: boot, `dnf`, two downloads, a certificate), select the instance and
   choose **Actions**, **Monitor and troubleshoot**, **Get system log**. AWS posts that log in bursts around state
   changes, so reload it after a minute if the last line has not appeared. These lines come in order, each stamped with
   the time, and the last is the signal:

   ```
   common-ground: Settings accepted (provider fake). Installing Python 3.13: Amazon's package, ...
   common-ground: Python 3.13.x at /usr/bin/python3.13
   common-ground: The site will be https://<ip with dashes>.nip.io/
   common-ground: The app answers on 127.0.0.1:8761 (provider fake). Waiting for the certificate.
   common-ground: Certificate ready after <n> seconds: https://<...>/ (python3.13, Caddy 2.11.7 with the SHA-512 matched, provider fake)
   ```

   Caddy's lines and the app's share that log. If ten minutes pass with no certificate the script says so and ends,
   while Caddy keeps retrying and its lines give the reason. When `nip.io` is rate-limited, launch again with
   `DNS_NAME=sslip.io` in the script: it is the same service under its other name.
5. Open `https://<ip with dashes>.nip.io/` in a private window and run the checks below.

In order, the script: checks its own settings before touching the machine; installs Python 3.13 from Amazon's
repositories, since `/usr/bin/python3` stays 3.9 for the life of the release and the app needs 3.11 or newer; asks the
metadata service (version 2, token first) for the public address; downloads the repository's `main` branch; writes the
settings file; downloads Caddy 2.11.7 and compares its SHA-512 with the value pinned in the script, which came from
the release's own checksum file, before running it; writes a three-line Caddyfile that sends the site name to
`127.0.0.1:8761`; starts both services; and waits for a certificate. The app listens on loopback and answers to the
public name only. Caddy ends TLS, redirects HTTP to HTTPS, passes `Host`, `Origin` and `Sec-Fetch-Site` through
untouched, and discards any `X-Forwarded-For` a client sent in favour of its own, ending in the client's address, which
is what `COMMON_GROUND_TRUST_PROXY=1` reads. `request_buffers 64KB` makes Caddy attach a `Content-Length` to every
request body up to that size, because the server refuses a body without one.

**Do not stop the instance.** There is no Elastic IP, so the public address survives a reboot but not a stop, and the
site name and its certificate are built from that address. Terminate the instance, with `common-ground-sg`, once
judging is over.

Charges: an instance and a public IPv4 address both accrue by the hour, drawn from credits on a free-plan account, so
look at the Billing page first. This guide never asks for a card.

## Checking that it works

Run these against the hosted address in a private window, after Render shows **Live** or the log reports a ready
certificate.

1. `GET /healthz` answers `ok`, and does so for a foreign `Host` as well; the page and the API refuse one.
2. Open the page. The top banner should name the mode you chose (**Synthetic sample data. Qloo is not being called.**
   for `fake`), with no plain-HTTP banner and no "does not label requests" banner.
3. In the browser's developer console on the page, run

   ```js
   const s = await (await fetch("/api/state")).json(); console.log(s.actor, s.actorWhy, s.limiterKey, s.mode)
   ```

   A good answer under `fake` reads `person same_origin forwarded` and a mode of `source: "fake"`, `key: "missing"`,
   `shapesVerified: false` (`source: "live"` and `key: "set"` under `live`). `shapesVerified` becomes `true` only when
   the probe's block is in the code. If `actorWhy` says `no_fetch_metadata`, something between the browser and the server
   strips the `Sec-Fetch-*` labels and no person's click will count; on Render that would be its proxy, so read this
   line first. A `limiterKey` of `forwarded` means the proxy's address is trusted correctly; `peer` means all visitors
   look like one client to the workspace-creation limit (the total of 120 a minute still holds).
4. Type `/api/state` into the address bar of the same browser instead. It answers `agent` and `typed_address`: an address
   typed into the bar is never a click.
5. Walk the page: **Try the sample group**, **Resolve** each person's matches (the button must work), choose the kind,
   **Compare places**, open a card, **Pick**, **Draft the invitation**, name the sender, **Sign off**, and finally ask the
   agent console to pick a place, which must answer `not_a_tool`.
6. Take the agent address the page shows. `curl <agent address>/tools` should list eight tools and none of the seven
   human verbs, and an MCP client that speaks Streamable HTTP can be pointed at `<agent address>/mcp`. From a clone,
   `python3 -m common_ground mcp --address <agent address>` stands in for a client that only speaks stdio.
7. **Does Render's free service sleep? (Render only.)** Close every tab and wait 20 minutes, then load the address and
   time it. About a minute behind a loading page means it slept, as intended. An instant answer means Render's health
   checks count as traffic: clear the Health Check Path (Settings, Health Checks, Edit, empty, Save Changes), wait
   another 20 minutes and try again. If it still never sleeps, two free services in one workspace cannot both last the
   month, and one of them should move to EC2 or be suspended until judging starts.

## If something looks wrong

| What you see | Likely meaning | What to do |
|---|---|---|
| Render deploy fails; the log says `key: missing` | the provider is `live` and `QLOO_API_KEY` is empty | paste the key, or set the provider to `fake` |
| Render deploy fails; the log names `COMMON_GROUND_ALLOWED_HOSTS` | `RENDER_EXTERNAL_HOSTNAME` was empty | set `COMMON_GROUND_ALLOWED_HOSTS` to the name the dashboard shows |
| Render deploy fails with `python: command not found` | the runtime has no `python` on its path | change the Start Command to `python3 -m common_ground serve` |
| Render deploy fails; no open port found | the program is not listening on `PORT` | check `PORT` is `10000` and `COMMON_GROUND_BIND` is `0.0.0.0` |
| `/healthz` says `ok` but the page is 403 `bad_host` | the `Host` the proxy forwards is not the allowed name | set `COMMON_GROUND_ALLOWED_HOSTS` to the `onrender.com` name; if that fails the proxy rewrites `Host`, so use EC2 |
| The page says "Live mode is on, but Qloo's response shapes have not been checked" | `live` chosen before the probe | set the provider to `fake` until the probe has run |
| 502 from the EC2 address | the app is not running | read the system log; the app's lines give the reason (a wrong key shows as a 401 from Qloo, not a crash) |
| The browser warns about the certificate | Caddy has none yet, or fell back to a staging one | wait, then read Caddy's lines in the system log |
| `actorWhy` is `no_fetch_metadata` on the HTTPS page | the labels are removed on the way | the human verbs cannot work there; use the other host |
| Render shows its loading page | the free service is waking | wait about a minute |

## Two services, one workspace, and the calendar

The author hosts a second service for the same hackathon in the same Render workspace. Both are created in **one sitting
on Sunday 25 October 2026**, the only day the owner is free. The first service's create click comes first and is also
the test for any card, phone or ID screen (if one appears, stop and use EC2 for both). The service in this guide comes
right after, with the same sign-in, and the owner repeats the create click. Because they share the 750 free hours, neither
is ever pinged awake. If the Sunday create fails or is not done, **Tuesday 27 October** is the retry, and the owner's
only touch is one create click on a form that is already filled. If Render fails the card, phone or ID test, the same
sitting uses the EC2 wizard instead, with the key typed into the marked line.

The hours reset on 1 November, before judging starts on 2 November. Read the hours used on the Billing page at the
sitting.

## When judging is over

The hosted demo has to stay up until judging ends (16 November), and a little beyond. After that, suspend or delete the
Render service; on EC2, terminate the instance and delete `common-ground-sg`.

## What no one could check without an account

The first sitting reads these:

- That Render's `python` is the version `.python-version` names, and that the deploy log says so.
- That Render's proxy forwards `Host` and `Sec-Fetch-Site` unchanged and appends exactly one `X-Forwarded-For` value.
  The pages read do not describe the proxy's headers; checks 3 and 4 above read both.
- Whether Render's health checks keep a free service awake (check 7).
- Whether Render asks for a card, a phone or an ID at sign-up or at the create click. Its first-deploy tutorial says no
  payment is required.
- That Let's Encrypt issues for the `nip.io` name at the first attempt, that the account's policy allows the new instance
  and security group, and that the console's field names match the table.
- That Caddy 2.11.7 accepts the three-line Caddyfile as written: no Caddy was run while writing this guide.
- The times quoted above, which are estimates.

## Pages read, and when

All on 21 Oct 2026.

- Render, under `https://render.com/docs/`: `free.md` (750 hours per workspace, spin-down after 15 minutes without
  inbound traffic, suspension, ephemeral filesystem), `web-services.md` (the form's fields, binding `0.0.0.0` and `PORT`,
  default 10000), `health-checks.md` (HTTP checks on a path; a 2xx or 3xx within five seconds passes; a deploy that keeps
  failing is cancelled after 15 minutes), `environment-variables.md` (`RENDER_EXTERNAL_HOSTNAME`, `PORT`),
  `configure-environment-variables.md`, `python-version.md` (default 3.14.8 for services created from 12 Oct 2026, the
  `.python-version` file, the `PYTHON_VERSION` variable taking precedence), `deploys.md` (build and start commands,
  auto-deploy options), `blueprint-spec.md` (the default plan, `buildCommand: 'true'`), `regions.md` and
  `troubleshooting-deploys.md`.
- AWS: `https://docs.aws.amazon.com/linux/al2023/ug/python.html` (versions 3.11 to 3.14 are packaged; `/usr/bin/python3`
  stays 3.9), the Amazon Linux 2023 package list for release 2023.12.20260930 (`python3.13` is 3.13.15), the EC2 user
  data page (16 KB, run as root at first boot only, kept afterwards), the launch wizard page and the instance console
  output page (**Actions**, **Monitor and troubleshoot**, **Get system log**).
- Caddy: `https://caddyserver.com/docs/automatic-https` (an IP address gets no publicly trusted certificate, so a name
  is needed; the HTTP challenge needs port 80; failures are retried, using Let's Encrypt's staging environment while
  retrying), `.../docs/running` (the service user and its writable home), `.../docs/install` (static binaries from the
  GitHub releases), `.../docs/caddyfile/directives/reverse_proxy` (`Host` passes through, client-sent `X-Forwarded-*`
  values are ignored, `request_buffers` sets `Content-Length`), and the v2.11.7 release's `checksums.txt` on GitHub.
- `https://sslip.io/`: `nip.io` and `sslip.io` are one service; a certificate for a name comes by the HTTP challenge;
  when one is rate-limited, try the other domain.
