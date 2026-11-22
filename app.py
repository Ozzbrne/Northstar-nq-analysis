from flask import Flask, jsonify, render_template
import requests, pandas as pd, numpy as np
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

app = Flask(__name__)
ET = ZoneInfo('America/New_York')
TICKERS = {'NQ':'NQ=F','ES':'ES=F','YM':'YM=F','RTY':'RTY=F','VIX':'^VIX','DXY':'DX-Y.NYB'}


def fetch_chart(symbol, interval='5m', range_='5d'):
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    r = requests.get(url, params={'interval':interval,'range':range_,'includePrePost':'true'}, headers={'User-Agent':'Mozilla/5.0'}, timeout=12)
    r.raise_for_status()
    j=r.json()['chart']['result'][0]
    ts=j.get('timestamp',[]); q=j['indicators']['quote'][0]
    df=pd.DataFrame({'time':pd.to_datetime(ts,unit='s',utc=True),'open':q.get('open'),'high':q.get('high'),'low':q.get('low'),'close':q.get('close'),'volume':q.get('volume')})
    df=df.dropna(subset=['close']).reset_index(drop=True)
    return df

def score_series(df):
    if len(df)<25: return 0
    closes=df.close.astype(float); ema9=closes.ewm(span=9).mean().iloc[-1]; ema21=closes.ewm(span=21).mean().iloc[-1]
    delta=float(closes.iloc[-1]-closes.iloc[-6]); pct=delta/max(float(closes.iloc[-6]),1)*100
    return float(np.clip((1 if ema9>ema21 else -1)*35 + np.clip(pct*22,-45,45),-100,100))

def market_snapshot():
    raw={}; errors={}
    for k,s in TICKERS.items():
        try: raw[k]=fetch_chart(s,'5m','5d')
        except Exception as e: errors[k]=str(e)[:140]
    if 'NQ' not in raw or len(raw['NQ'])<30:
        raise RuntimeError('NQ market data is unavailable from the public feed right now. Try refresh in a minute.')
    nq=raw['NQ']; close=float(nq.close.iloc[-1]); last=nq.iloc[-1]
    # Session VWAP approximation based on the most recent US trading session date.
    et_dates=nq.time.dt.tz_convert(ET).dt.date
    nq_session=nq[et_dates==et_dates.iloc[-1]].copy()
    vol=nq_session.volume.fillna(0).astype(float); typical=(nq_session.high+nq_session.low+nq_session.close)/3
    vwap=float((typical*vol).sum()/vol.sum()) if vol.sum()>0 else float(nq_session.close.mean())
    ema9=float(nq.close.ewm(span=9).mean().iloc[-1]); ema21=float(nq.close.ewm(span=21).mean().iloc[-1]); ema50=float(nq.close.ewm(span=50).mean().iloc[-1])
    recent=nq.tail(36); swing_hi=float(recent.high.max()); swing_lo=float(recent.low.min())
    # Structure: compare recent 12-bar extrema with prior 12-bar extrema.
    a=nq.tail(12); b=nq.iloc[-24:-12]
    structure=0
    if a.high.mean()>b.high.mean() and a.low.mean()>b.low.mean(): structure=75
    elif a.high.mean()<b.high.mean() and a.low.mean()<b.low.mean(): structure=-75
    elif close>ema21: structure=25
    elif close<ema21: structure=-25
    # Momentum mix
    mom=float(np.clip((close-ema9)/max(close,1)*10000*8 + (35 if ema9>ema21 else -35),-100,100))
    # Location score: vwap and range position
    vscore=45 if close>vwap else -45
    range_pos=(close-swing_lo)/max(swing_hi-swing_lo,1e-9)
    location=float(np.clip(vscore + (range_pos-.5)*50,-100,100))
    # Intermarket, compare short directional EMA score of indexes; VIX and DXY inverse bias modestly.
    inter=[]; notes=[]
    for key in ('ES','YM','RTY'):
        if key in raw:
            s=score_series(raw[key]); inter.append(s); notes.append(f'{key} {"supportive" if s>10 else "weak" if s<-10 else "mixed"}')
    if 'VIX' in raw:
        vix=float(raw['VIX'].close.iloc[-1]); vix_prev=float(raw['VIX'].close.iloc[-6]) if len(raw['VIX'])>6 else vix
        inter.append(float(np.clip((vix_prev-vix)/max(vix,1)*1000,-35,35)))
    if 'DXY' in raw: inter.append(-score_series(raw['DXY'])*.35)
    intermarket=float(np.mean(inter)) if inter else 0
    # Volatility environment and session-context scores
    returns=nq.close.pct_change().dropna(); vol_now=float(returns.tail(12).std()); vol_base=float(returns.tail(60).std()) if len(returns)>60 else vol_now
    vol_score=float(np.clip((close-ema21)/max(close,1)*10000*5,-50,50))
    etnow=datetime.now(ET); minutes=etnow.hour*60+etnow.minute; rth=570<=minutes<960
    session_score=float(np.clip((close-vwap)/max(close,1)*10000*3,-55,55)) if rth else float(np.clip((close-ema21)/max(close,1)*10000*2,-40,40))
    cats={'Structure':structure,'Liquidity / Location':location,'Momentum':mom,'Intermarket':intermarket,'Volatility':vol_score,'Session Context':session_score}
    weights={'Structure':.25,'Liquidity / Location':.20,'Momentum':.20,'Intermarket':.15,'Volatility':.10,'Session Context':.10}
    total=sum(cats[k]*weights[k] for k in cats)
    bias='Strong Bullish' if total>=40 else 'Bullish' if total>=20 else 'Strong Bearish' if total<=-40 else 'Bearish' if total<=-20 else 'Neutral / Mixed'
    aligned=sum(1 for x in cats.values() if (total>0 and x>10) or (total<0 and x<-10))
    conviction='High' if abs(total)>=40 and aligned>=4 else 'Moderate' if abs(total)>=20 and aligned>=3 else 'Low'
    bull='Bull case strengthens if price holds above VWAP and reclaims the recent range high.'
    bear='Bear case strengthens if price loses VWAP and breaks the recent range low.'
    if total>20: bull='Bullish continuation requires acceptance above VWAP; watch the recent swing high for liquidity.'
    if total<-20: bear='Bearish continuation requires acceptance below VWAP; watch the recent swing low for liquidity.'
    return {'timestamp':datetime.now(timezone.utc).isoformat(),'local_time':etnow.strftime('%Y-%m-%d %H:%M:%S ET'),'price':close,'change':float(close-nq.close.iloc[-2]),'vwap':vwap,'ema9':ema9,'ema21':ema21,'ema50':ema50,'swing_high':swing_hi,'swing_low':swing_lo,'range_position':round(range_pos*100,1),'score':round(total,1),'bias':bias,'conviction':conviction,'categories':cats,'weights':weights,'bull_case':bull,'bear_case':bear,'market_notes':notes,'volatility_ratio':round(vol_now/max(vol_base,1e-12),2),'data_errors':errors,'data_note':'Public Yahoo Finance feed; may be delayed, incomplete, or rate-limited. VWAP and structure are approximations based on retrieved candles. No footprint, TPO, or order-flow data.'}

@app.route('/')
def home(): return render_template('index.html')
@app.route('/api/market')
def market():
    try: return jsonify(market_snapshot())
    except Exception as e: return jsonify({'error':str(e)}),503
@app.route('/health')
def health(): return jsonify({'status':'ok'})
if __name__=='__main__': app.run(host='0.0.0.0',port=10000)
