# Northstar NQ Research Lab
A lightweight rules-based NQ market context dashboard using public Yahoo Finance chart data. No AI API key is required.


## Deploy to Render
1. Upload this folder to a new GitHub repository named `northstar-nq-research-lab` (the files must be at the repository root, not nested inside another folder).
2. In Render choose **New > Blueprint** and connect that repository. Render will read `render.yaml` and create the web service.
3. Alternatively create a Web Service, connect the repository, set Build Command `pip install -r requirements.txt`, Start Command `gunicorn app:app`.

## Data and limitations
- Data is requested from Yahoo Finance public chart endpoints; may be delayed, rate limited, or unavailable. This is not a guaranteed real-time exchange feed.
- Factor calculations are rough candle-based proxies and should be reviewed/validated. VWAP is estimated from the most recent retrieved session candles.
- Does not provide footprint/prints, TPO, actual order flow, or execution. Not financial advice.
