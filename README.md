# TempRadar calibration data

This branch holds the data behind the "Track record" on https://klevi2.github.io/tempradar/.
It is written by GitHub Actions; the code lives on the `main` branch.

| Path | Written by | Content |
|---|---|---|
| `forecasts/<date>/<slot>.json` | `telegram.yml`, after each Telegram post | The full bucket distribution behind the post: every bucket with its share of the 161 ensemble members, plus the model consensus |
| `outcomes/<date>.json` | `score.yml`, daily | The measured daily high per station, Polymarket rule: routine METARs only, T-group in tenths of °C, local calendar day, rounded halves up; from aviationweather.gov |
| `calibration.json` | `score.yml`, daily | Summary: for each 10% probability band, how often those buckets came true; top-bucket hit rate; Brier score; consensus bias and mean absolute error, overall, per post and per station |

`slot` is `morning` (today's highs), `noon` (tomorrow's) or `evening` (tomorrow's, after the 12Z runs).
Data starts on 20 November 2026; no earlier forecasts were kept.
