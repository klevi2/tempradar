# TempRadar

**Live: [klevi2.github.io/tempradar](https://klevi2.github.io/tempradar/)**

A free web page for people trading daily high-temperature markets on Polymarket and Kalshi. For each settlement station it shows:

- **Model consensus**: the average daily high of up to nine weather models.
- **Bucket chances**: the share of 161 ensemble members that land in each market bucket.
- **Today so far**: the highest temperature measured since local midnight, with when it was reached and how recent the data is.

It is a data page only. It gives no trading advice and promises no profit, and it is not affiliated with Polymarket, Kalshi or any weather agency.

Everything runs in the visitor's browser. There is no server, no account and no API key.

## How the numbers are made

| What | Source | Method |
|---|---|---|
| Consensus | [Open-Meteo](https://open-meteo.com/) forecast API | Mean of ECMWF IFS, ECMWF AIFS, GFS, ICON, GEM, UK Met Office, Météo-France and JMA, plus NBM for US stations. Daily maximum for the station's local calendar day at the station's coordinates and elevation. |
| Bucket chances | Open-Meteo ensemble API | 161 members: ECMWF ENS 51, GEFS 31, ICON EPS 40, GEM GEPS 21, MOGREPS-G 18. Each member's daily high is rounded to a whole degree (halves up) and counts once. |
| Buckets | Market rules | °F: two degrees wide, starting on an even number (80–81), as on Polymarket. °C: one degree. Kalshi moves its °F edges from day to day, so Kalshi rows have an even/odd bucket-start switch. |
| Today so far | [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/) (IEM), with [api.weather.gov](https://www.weather.gov/documentation/services-web-api) as fallback for US stations | Polymarket rule: routine METARs only, temperature from the RMK T-group in tenths of °C (body group if missing), converted to °F and rounded halves up. “High at” is the time of that report; “data to” is the newest report, flagged when it is more than 75 minutes old. The detail panel also shows the six-hour maximum group and, for US Kalshi stations, the highest five-minute reading. Hong Kong is not covered (it settles on the Observatory's own reading). |

On the **Today** view, ensemble members below the measured high are counted at the measured high, since the day's final high cannot be lower than what was already measured.

### Known limits

- A model grid cell is not the airport thermometer. Coastal, lake-side and mountain stations can be several degrees off.
- Ensemble daily highs are built from hourly or three-hourly values and tend to miss short peaks. The spread is raw, not calibrated.
- Neither data source marks SPECI reports reliably: api.weather.gov drops the prefix, and IEM's own "routine" type keeps one report per hour, which would lose London's :20 reports. The page treats the station's usual reporting minutes (KLGA :51, EGLC :20 and :50) as routine and lists a higher off-minute report separately.
- Data can run late. On 19 Nov 2026, api.weather.gov was up to two hours behind the official METAR feed for US stations, and IEM was two hours behind for Taipei. The page shows "data to" and a warning, but it cannot fetch aviationweather.gov directly (no CORS).
- Kalshi lists The Weather Company (weather.com/kalshi) as its source. Its figure can differ from the NWS climate report.

## Stations

`stations.js` holds the 65 stations and the model settings. The web page and the Telegram script both read it, so they always compute the same thing.

The list was checked against every open Polymarket and Kalshi daily-high market on **18 November 2026**:

- **Polymarket (49 cities)**: station ICAO codes come from each market's resolution source (aviationweather.gov METAR link). Coordinates and elevation come from the aviationweather.gov station database. Hong Kong settles on the Hong Kong Observatory instead of a METAR.
- **Kalshi (24 series)**: each market names an NWS climate code (CLINYC, CLIMDW, …). The ICAO station is inferred from that code, so these rows carry an *Unverified* flag.
- Eight stations are used by both platforms (Atlanta, Austin, Denver, Houston Hobby, Los Angeles, Miami, San Francisco, Seattle).

Pairs that are easy to mix up:

| City | Polymarket | Kalshi |
|---|---|---|
| New York | LaGuardia (KLGA) | Central Park (KNYC) |
| Chicago | O'Hare (KORD) | Midway (KMDW) |
| Dallas | Love Field (KDAL) | DFW Airport (KDFW) |
| Paris | Le Bourget (LFPB), not CDG | none open |

Day definition: Polymarket counts reports whose local time, including daylight saving, falls on the date. The NWS climate day that Kalshi relies on uses local standard time, so during daylight saving it runs from 1:00 a.m. to 12:59 a.m.

Markets are added and changed often. Read the rules of the market you trade, and update `stations.js` when a station changes. Each station is one JSON line, and the JSON between the two marker comments must stay valid.

## Daily Telegram post

Channel: [t.me/tempradar_wx](https://t.me/tempradar_wx). `scripts/post_telegram.py` posts tomorrow's consensus and three most likely buckets for the stations marked `"telegram": true` in `stations.js` (eight by default). `.github/workflows/telegram.yml` runs it every day at 12:15 UTC. It uses only the Python standard library.

Setup:

1. In Telegram, create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Create a channel, and add the bot as an administrator that can post messages.
3. In the GitHub repository, open **Settings → Secrets and variables → Actions** and add:
   - secret `TELEGRAM_BOT_TOKEN`: the bot token
   - secret `TELEGRAM_CHAT_ID`: `@yourchannel` for a public channel, or the numeric `-100…` id for a private one
   - optional variable (not secret) `SITE_URL`: the site address for the link at the end of the post (default: https://klevi2.github.io/tempradar/)
4. Open **Actions → Daily Telegram post → Run workflow**. A run with *dry run* ticked only prints the message in the log; untick it to send a real post.

The token and chat id live only in GitHub Secrets. They are never written to the code or printed in the log.

GitHub turns off scheduled workflows in a public repository after 60 days without repository activity. If posts stop, re-enable the workflow on the Actions tab or push a commit.

## Visitor statistics

Visits are counted with [GoatCounter](https://www.goatcounter.com/) (site code `tempradarwx`, dashboard at tempradarwx.goatcounter.com). GoatCounter sets no cookies and stores no personal data, so the page needs no cookie banner. Visits from localhost and `file://` are not counted.

## Run it locally

Open `index.html` in a browser. All data requests go straight to the public APIs. Chrome refuses to load web fonts from `file://`, so the page falls back to the system font there. For the real font, serve the folder over HTTP, for example with `npx serve .`.

Tests: `python3 tests/test_parity.py` (needs Node.js) checks that `calc.js` and `scripts/tempradar_calc.py` give identical results on saved ensemble data and edge cases. `node tests/metar_test.js` checks the METAR and observation helpers. GitHub Actions runs both on every push.

Telegram post without sending: `DRY_RUN=1 python3 scripts/post_telegram.py`. On Windows, first run `python -m pip install tzdata`, because Windows has no built-in time zone database.

## Files

| Path | Purpose |
|---|---|
| `index.html` | The page: layout, styles, data loading |
| `calc.js` | Calculation core: rounding, buckets, consensus, METAR parsing |
| `stations.js` | Stations and model settings, shared with Python |
| `scripts/tempradar_calc.py` | Python port of `calc.js` |
| `scripts/post_telegram.py` | Daily Telegram post |
| `tests/` | Parity test and saved fixtures |
| `fonts/` | Barlow, self-hosted (SIL Open Font License, see `fonts/OFL.txt`) |

## Free-tier limits

Open-Meteo's free API is for non-commercial use: up to 10,000 calls a day, 5,000 an hour and 600 a minute, counted per visitor IP address. One ensemble load counts as about 16 calls. The page therefore loads ensembles only for pinned or opened stations, and caches responses in the browser for 30–60 minutes. Paid features would need an Open-Meteo commercial plan.

IEM's METAR service allows one request per second per IP address and asks clients to fetch many stations in one request ([service notes](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help)). The page loads measurements only for the stations on screen (the selected station and the featured one), asks for them in a single request, keeps at least 1.1 seconds between requests, caches each station for 5 minutes, and pauses for a minute after a 429 or 503 answer (US stations then use api.weather.gov). IEM data is public domain; it asks for attribution, which the page footer gives.

## Credits and licence

Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). METAR observations come from the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/) of Iowa State University (public domain, attribution appreciated), with the US National Weather Service (public domain) as fallback. The Barlow typeface is by Jeremy Tribby, under the SIL Open Font License 1.1.
