# -*- coding: utf-8 -*-
import os
import re
import json
import time
import math
import requests
import feedparser
import pandas as pd
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from unidecode import unidecode
import streamlit as st
from openai import OpenAI

# --- içerik çıkarımı
import trafilatura
from bs4 import BeautifulSoup

# =========================
# APP CONFIG
# =========================
st.set_page_config(page_title="Tesis Adı Çıkarımı – Grok (Yerel + Metin)", layout="wide")
st.title("🏭 Tesis Adı Çıkarımı – Grok (Yerel haber gövdesinden)")

GROK_API_KEY = os.getenv("GROK_API_KEY")
if not GROK_API_KEY:
    st.error("GROK_API_KEY ortam değişkeni tanımlı değil.")
    st.stop()

client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

DEFAULT_MODEL = "grok-3"  # erişiminize göre grok-4 veya grok-4-fast-reasoning
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FacilityExtractBot/1.0; +https://example.com)"
}

LOCAL_HINTS = [
    ".bel.tr",".gov.tr",".edu.tr",".k12.tr",".osb",".osb.org",".org.tr",
    "haber","sondakika","yerel","manset","gazete","kent","kenthaber","medya"
]

# =========================
# YARDIMCI FONKSİYONLAR
# =========================
def norm(s: str) -> str:
    if not s: return ""
    s = unidecode(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def google_news_rss_query(keywords: str, days: int = 7) -> str:
    q = requests.utils.quote(f'({keywords}) when:{days}d')
    return f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"

def fetch_rss(keyword_list, days_back=7, max_per_kw=20):
    items = []
    for kw in keyword_list:
        url = google_news_rss_query(kw, days_back)
        feed = feedparser.parse(url)
        for e in feed.entries[:max_per_kw]:
            link = e.get("link","")
            title = e.get("title","")
            summary = e.get("summary","")
            published = e.get("published","") or e.get("updated","")
            try:
                dt = dateparser.parse(published)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
            items.append({
                "kw": kw,
                "title": title,
                "summary": summary,
                "link": link,
                "published": dt
            })
        time.sleep(0.3)  # nazik davran
    return items

def domain_score(u: str) -> int:
    try:
        d = urlparse(u).netloc.lower()
    except Exception:
        return 0
    score = 0
    for hint in LOCAL_HINTS:
        if hint in d:
            score += 2
    if any(x in d for x in ["ntv","cnnturk","hurriyet","sozcu","sabah","aa.com.tr","dha.com.tr"]):
        score -= 1
    return score

def rank_and_pick(items, start_dt, end_dt, limit=20, only_local=True):
    items = [it for it in items if isinstance(it["published"], datetime) and start_dt <= it["published"] <= end_dt]
    for it in items:
        it["score"] = domain_score(it["link"])
    if only_local:
        items = [it for it in items if it["score"] >= 1]
    items = sorted(items, key=lambda x: (x["score"], x["published"]), reverse=True)
    return items[:limit]

def resolve_and_fetch(url: str, timeout=12) -> tuple[str, str]:
    """
    Google News yönlendirme linklerini kanonik habere çözüp HTML içeriğini getir.
    returns: (final_url, html)
    """
    try:
        r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=timeout)
        final_url = r.url
        html = r.text
        # Bazı siteler JS ile yönlendirir; <meta http-equiv="refresh"> yakala
        if "<meta http-equiv" in html.lower() and "url=" in html.lower():
            soup = BeautifulSoup(html, "html.parser")
            meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
            if meta and "content" in meta.attrs:
                m = re.search(r'url=(.+)', meta["content"], re.I)
                if m:
                    next_url = m.group(1).strip().strip("'\"")
                    r2 = requests.get(next_url, headers=HEADERS, allow_redirects=True, timeout=timeout)
                    final_url = r2.url
                    html = r2.text
        return final_url, html
    except Exception:
        return url, ""

def extract_main_text(html: str) -> str:
    """
    Öncelik trafilatura; başarısızsa basit BeautifulSoup <p> fallback.
    """
    if not html:
        return ""
    try:
        txt = trafilatura.extract(html, include_tables=False, include_comments=False, include_images=False)
        if txt and len(txt) > 200:
            return txt
    except Exception:
        pass
    # fallback
    try:
        soup = BeautifulSoup(html, "html.parser")
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        txt = "\n".join(ps)
        return txt
    except Exception:
        return ""

def truncate(s: str, n: int) -> str:
    if not s: return s
    return s if len(s) <= n else s[: n-3] + "..."

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

# =========================
# GROK TESİS ADI ÇIKARIMI
# =========================
SYSTEM_PROMPT = """
Sigorta amaçlı bilgi çıkarımı yapıyorsun.
Aşağıda her biri için title, url ve article_text (haber gövdesi) verilecek.
Görevin: metne DAYANARAK, olay başına TESİS ADI'nı tespit etmek.
Kurallar:
- Metinde açık unvan/isim geçiyorsa 'tesis_ad_teyit' = TEYITLI ve adı metindeki haliyle yaz.
- Metin yalnızca sektörü/mahalleyi ima ediyorsa 'TAHMIN'.
- Tesis adı bulunmuyorsa 'TEYIT_EDILEMEDI'.
- JSON dizi döndür; alanlar:
  olay_tarihi (YYYY-MM-DD veya null), sehir, ilce, tesis_adi,
  tesis_ad_teyit (TEYITLI|TAHMIN|TEYIT_EDILEMEDI),
  kanit_linkleri ([url]), aciklama, guven_skoru (0..1).
- Uydurma yapma; metinde yoksa TEYIT_EDILEMEDI de.
- SADECE ham JSON dizi yaz.
"""

@st.cache_data(show_spinner=False, ttl=900)
def grok_extract_from_articles(model: str, docs: list):
    # docs: [{"url","title","text","published"}]
    compact = []
    for d in docs:
        compact.append({
            "url": d["url"],
            "title": truncate(unidecode(d["title"] or ""), 220),
            "published": d["published"].strftime("%Y-%m-%d %H:%M") if isinstance(d["published"], datetime) else "",
            "article_text": truncate(unidecode(d["text"] or ""), 2000)  # token tasarrufu
        })
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {"role": "user", "content": json.dumps({"articles": compact}, ensure_ascii=False)}
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=2400,
        temperature=0.0
    )
    content = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\[.*\]\s*$", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []

# =========================
# UI – Parametreler
# =========================
with st.sidebar:
    st.header("Sorgu Ayarları")
    today = datetime.now(timezone.utc).date()
    end_date = st.date_input("Bitiş Tarihi", value=today)
    days_back = st.slider("Geri Gün", 1, 30, 7)
    start_dt = datetime.combine(end_date - timedelta(days=days_back), datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    st.markdown("**Anahtar Kelimeler (satır satır)**")
    default_kws = [
        "fabrika yangın", "tesis yangın", "sanayi yangını", "OSB yangın",
        "patlama fabrika", "kimyasal sızıntı", "rafineri yangın", "trafo patlaması"
    ]
    kw_text = st.text_area("Kelimeler", "\n".join(default_kws), height=150)

    only_local = st.checkbox("Sadece yerel domainleri seç", value=True)
    max_links = st.slider("Toplanacak haber sayısı", 5, 80, 24, step=1)
    fetch_timeout = st.slider("HTML indirme zaman aşımı (sn)", 6, 20, 12)
    text_minlen = st.slider("Gerekli minimum metin uzunluğu", 200, 1500, 400, step=50)

    model_name = st.selectbox("Grok Modeli", [DEFAULT_MODEL, "grok-4", "grok-4-fast-reasoning"], index=0)
    batch_size = st.slider("Grok batch boyutu", 3, 20, 8, step=1)

run = st.button("Tesis Adlarını Çıkar")

st.markdown("---")

# =========================
# ÇALIŞTIR
# =========================
if run:
    keywords = [k.strip() for k in kw_text.splitlines() if k.strip()]

    with st.spinner("RSS kaynakları çekiliyor..."):
        raw = fetch_rss(keywords, days_back=days_back, max_per_kw=20)
    st.success(f"RSS'ten {len(raw)} aday haber geldi.")

    picked = rank_and_pick(raw, start_dt, end_dt, limit=max_links, only_local=only_local)
    if not picked:
        st.warning("Seçilen aralık/filtre ile uygun link bulunamadı. 'Sadece yerel' filtresini kapatıp deneyin.")
        st.stop()

    # HTML getir + metin çıkar
    docs = []
    ok, fail = 0, 0
    for it in picked:
        final_url, html = resolve_and_fetch(it["link"], timeout=fetch_timeout)
        if not html:
            fail += 1
            continue
        text = extract_main_text(html)
        if not text or len(text) < text_minlen:
            fail += 1
            continue
        docs.append({
            "url": final_url,
            "title": it["title"],
            "published": it["published"],
            "text": text
        })
        ok += 1
        time.sleep(0.4)  # nazik

    st.info(f"Metin çıkarımı: başarı={ok}, başarısız={fail}. Grok'a {len(docs)} makale gönderilecek.")
    if not docs:
        st.warning("Yeterli metin çıkarılamadı. Minimum metin uzunluğunu düşürüp tekrar deneyin.")
        st.stop()

    # Kaynak önizleme
    prev = pd.DataFrame([{"published": d["published"], "domain": urlparse(d["url"]).netloc,
                          "title": d["title"], "len(text)": len(d["text"])} for d in docs])
    st.dataframe(prev, use_container_width=True)

    # Grok batch
    results = []
    for chunk in chunks(docs, batch_size):
        with st.spinner(f"Grok çıkarım yapıyor... ({len(chunk)} makale)"):
            out = grok_extract_from_articles(model_name, chunk)
            results.extend(out)
        time.sleep(0.8)

    if not results:
        st.warning("Grok, sağlanan metinlerden tesis adı çıkaramadı. Text/limit/batch parametrelerini ayarlayın.")
        st.stop()

    # Sonuçlar
    df = pd.DataFrame(results)
    for c in ["olay_tarihi","sehir","ilce","tesis_adi","tesis_ad_teyit","guven_skoru","aciklama","kanit_linkleri"]:
        if c not in df.columns:
            df[c] = None

    st.subheader("🔎 Çıkarılan Tesis Adları")
    st.dataframe(df[["olay_tarihi","sehir","ilce","tesis_adi","tesis_ad_teyit","guven_skoru","aciklama"]], use_container_width=True)

    st.subheader("🔗 Kanıt Linkleri")
    for i, row in df.iterrows():
        links = row.get("kanit_linkleri") or []
        if links:
            st.markdown(f"**Olay {i+1} – {row.get('tesis_adi') or 'Tesis?'}**")
            for L in links[:6]:
                st.markdown(f"- {L}")

    st.success("Tamam. Bu çıktı üzerine doğrulama/harita/PD-BI adımlarını ekleyebiliriz.")
else:
    st.info("Parametreleri seçip 'Tesis Adlarını Çıkar' butonuna basın. Bu adım yalnızca tesis adını tespit eder.")
