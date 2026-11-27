import os, json, datetime as dt, requests, yfinance as yf
KEY = os.environ["ECOS_KEY"]
now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))

def ecos(stat, item, cycle="D"):
    start = (now - dt.timedelta(days=1200)).strftime("%Y%m%d")
    u = f"https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/100000/{stat}/{cycle}/{start}/{now:%Y%m%d}/{item}"
    rows = requests.get(u, timeout=30).json()["StatisticSearch"]["row"]
    return [(r["TIME"], float(r["DATA_VALUE"])) for r in rows if r["DATA_VALUE"]]

# 1) 금리 (ECOS 817Y002 시장금리 일별 / 항목코드는 첫 실행 후 ECOS에서 확인)
RATES = [("국고채 3년","010200000"),("국고채 5년","010200001"),("국고채 10년","010210000"),
         ("국고채 20년","010220000"),("국고채 30년","010230000"),("회사채 AA- 3년","010300000"),("CD 91일","010190000")]
rates, t10 = [], []
for n, c in RATES:
    try:
        s = ecos("817Y002", c)
        if c == "010210000": t10 = s
        rates.append({"name": n, "value": s[-1][1], "chg": round((s[-1][1]-s[-2][1])*100, 1)})
    except Exception as e: print(n, e)

# 2) 재정검증 할인율: 일별 -> 월평균 -> 최근 36개월 평균 -> 25bp 반올림
m = {}
for d, v in t10: m.setdefault(d[:6], []).append(v)
mo = sorted(m)[-36:]
avg = sum(sum(m[k])/len(m[k]) for k in mo) / len(mo)
fiscal = {"base": mo[-1], "months": len(mo), "avg": round(avg, 3), "rate": int(avg*4+0.5)/4}

# 3) 지수·환율·원자재
T = [("KOSPI","^KS11"),("KOSDAQ","^KQ11"),("S&P500","^GSPC"),("나스닥","^IXIC"),("다우","^DJI"),
     ("닛케이225","^N225"),("VIX","^VIX"),("WTI","CL=F"),("금","GC=F"),("원/달러","KRW=X"),("원/100엔","JPYKRW=X")]
mk = []
for n, t in T:
    try:
        h = yf.Ticker(t).history(period="10d")["Close"].dropna()
        k = 100 if "JPY" in t else 1
        a, b = h.iloc[-1]*k, h.iloc[-2]*k
        mk.append({"name": n, "value": round(a, 2), "pct": round((a/b-1)*100, 2), "date": str(h.index[-1].date())})
    except Exception as e: print(n, e)

# 4) 경제 캘린더 (events.json 직접 관리, 14일 이내)
ev = [e for e in json.load(open("events.json", encoding="utf-8"))
      if 0 <= (dt.date.fromisoformat(e["date"]) - now.date()).days <= 14]
ev.sort(key=lambda e: e["date"])

# 5) 토킹포인트 (기본: 규칙 기반 / ANTHROPIC_API_KEY가 있으면 Claude가 작성)
r = {x["name"]: x for x in rates}; q = {x["name"]: x for x in mk}
talk = []
if "국고채 10년" in r:
    x = r["국고채 10년"]; c = x["chg"]
    msg = ("채권 매입 시점 설명에 유리한 흐름입니다." if c <= -3 else
           "금리 상승으로 신규 매입 수익률은 개선, 보유채권 평가손실은 유의하세요." if c >= 3 else "큰 변동 없이 안정적입니다.")
    talk.append(f"국고채 10년 {x['value']:.2f}% ({c:+.1f}bp). {msg}")
talk.append(f"재정검증 할인율 추정 {fiscal['rate']:.2f}% (10년 국고채 {fiscal['months']}개월 평균 {fiscal['avg']:.2f}%, 기준월 {fiscal['base']}).")
for n in ("KOSPI", "S&P500"):
    if n in q and abs(q[n]["pct"]) >= 1: talk.append(f"{n} 전일 대비 {q[n]['pct']:+.2f}%.")
if "원/달러" in q and abs(q["원/달러"]["pct"]) >= 0.5: talk.append(f"원/달러 {q['원/달러']['value']:,.1f}원 ({q['원/달러']['pct']:+.2f}%).")
if ev: talk.append(f"예정: {ev[0]['date'][5:]} {ev[0]['title']}")

out = {"updated": now.strftime("%Y-%m-%d %H:%M KST"), "asof": q.get("KOSPI", {}).get("date", ""),
       "talk": talk, "rates": rates, "fiscal": fiscal, "markets": mk, "events": ev}

k = os.environ.get("ANTHROPIC_API_KEY")
if k:
    try:
        res = requests.post("https://api.anthropic.com/v1/messages", timeout=60,
            headers={"x-api-key": k, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-5-5", "max_tokens": 600, "messages": [{"role": "user", "content":
              "퇴직연금 영업 담당자가 아침에 읽을 토킹포인트를 한국어 3~4줄로, 줄마다 한 문장으로 써줘. "
              "숫자는 아래 데이터에서만 쓰고 투자 권유는 하지 마.\n" + json.dumps(out, ensure_ascii=False)}]})
        out["talk"] = [l.strip("-• ") for l in res.json()["content"][0]["text"].splitlines() if l.strip()]
    except Exception as e: print("claude", e)

json.dump(out, open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
