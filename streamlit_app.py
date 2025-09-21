# -*- coding: utf-8 -*-
# Tesis Adı Çıkarımı – Grok (Yerel haber gövdesinden)
# Odak: Haberden TESİS ADI tespiti (PD/BI ve harita yok – sonraki adım)
import os
import re
import json
import time
import requests
import feedparser
import pandas as pd
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from unidecode import unidecode
import streamlit as st
from openai import OpenAI

# İçerik çıkarımı
import trafilatura
from bs4 import BeautifulSoup

# =========================
# APP CONFIG
# =========================
st.set_page_config(page_title="Tesis Adı Çıkarımı – Grok", layout="wide")
st.title("🏭 Tesis Adı Çıkarımı – Grok (Yerel haber gövdesinden)")

GROK_API_KEY = os.getenv("GROK_API_KEY")
if not GROK_API_KEY:
    st.error("GROK_API_KEY ortam değişkeni tanımlı değil. (x.ai anahtarınızı ekleyin.)")
    st.stop()

client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
DEFAULT_MODEL = "grok-4-fast-reasoning"  # erişiminize göre "grok-3" seçebilirsiniz

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
}

LOCAL_HINTS = [
    ".bel.tr",".gov.tr",".edu.tr",".k12.tr",".osb",".osb.org",".org.tr",
    "haber","sondakika","yerel","manset","gazete","kent","kenthaber","medya"
]

def norm(s: str) -> str:
    if not s: return ""
    s = unidecode(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# =========================
# RSS (deterministik çekiş)
# =========================
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
        score -= 1  # ulusala küçük ceza: yerel önceliği artır
    return score

def rank_and_pick(items, start_dt, end_dt, limit=30, only_local=True):
    items = [it for it in items if isinstance(it["published"], datetime) and start_dt <= it["published"] <= end_dt]
    for it in items:
        it["score"] = domain_score(it["link"])
    if only_local:
        items = [it for it in items if it["score"] >= 1]
    items = sorted(items, key=lambda x: (x["score"], x["published"]), reverse=True)
    return items[:limit]

# =========================
# HTML indirme + AMP çözümü + metin çıkarımı
# =========================
def _fetch(url: str, timeout=12):
    try:
        r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=timeout)
        return r.url, r.status_code, r.text
    except Exception:
        return url, None, ""

def resolve_and_fetch_with_amp(url: str, timeout=12):
    """
    1) Kanonik sayfayı indir
    2) AMP linkini ara → indir
    3) Meta-refresh varsa çöz
    """
    final_url, code, html = _fetch(url, timeout=timeout)
    amp_url = None

    if html:
        soup = BeautifulSoup(html, "html.parser")
        amp_link = soup.find("link", rel=lambda v: v and "amphtml" in v.lower())
        if amp_link and amp_link.get("href"):
            amp_url = amp_link["href"].strip()

        # bazen /amp tahmini işe yarar
        if not amp_url and "/amp" not in final_url:
            guess = re.sub(r"/$", "", final_url) + "/amp"
            amp_final, amp_code, amp_html = _fetch(guess, timeout=timeout)
            if amp_code and amp_code < 400 and len(amp_html) > 200:
                return amp_final, amp_code, amp_html, final_url, code, html

    if amp_url:
        amp_final, amp_code, amp_html = _fetch(amp_url, timeout=timeout)
        return amp_final, amp_code, amp_html, final_url, code, html

    # meta refresh
    if html and "<meta http-equiv" in html.lower() and "url=" in html.lower():
        soup = BeautifulSoup(html, "html.parser")
        m = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if m and m.get("content"):
            mt = m["content"]
            mm = re.search(r'url=(.+)', mt, re.I)
            if mm:
                nxt = mm.group(1).strip().strip("'\"")
                nfinal, ncode, nhtml = _fetch(nxt, timeout=timeout)
                return nfinal, ncode, nhtml, final_url, code, html

    return final_url, code, html, None, None, None

def extract_main_text_robust(html: str) -> str:
    """Önce trafilatura; olmazsa <article>, sonra <p>, en sonda og:description + title + h1."""
    if not html:
        return ""

    # 1) trafilatura
    try:
        txt = trafilatura.extract(html, include_tables=False, include_comments=False, include_images=False)
        if txt and len(txt) > 200:
            return txt
    except Exception:
        pass

    soup = BeautifulSoup(html, "html.parser")

    # 2) <article> birleşimi
    try:
        arts = soup.find_all("article")
        if arts:
            parts = [a.get_text(" ", strip=True) for a in arts if a]
            txt = "\n".join([p for p in parts if p])
            if len(txt) > 200:
                return txt
    except Exception:
        pass

    # 3) tüm <p> birleşimi
    try:
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        ptxt = "\n".join([p for p in ps if p])
        if len(ptxt) > 160:
            return ptxt
    except Exception:
        pass

    # 4) meta + başlıklar (kısa da olsa ipucu sağlar)
    try:
        og_desc = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
        ogd = og_desc.get("content").strip() if og_desc and og_desc.get("content") else ""
        h1 = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
        title = soup.find("title").get_text(" ", strip=True) if soup.find("title") else ""
        combo = " ".join([t for t in [h1, title, ogd] if t])
        return combo
    except Exception:
        return ""

def prepare_docs_for_grok(picked_items, fetch_timeout=12, min_accept_len=120):
    """
    Her link için: kanonik/AMP çöz → HTML → metin çıkar.
    min_accept_len: adaptif eşik; kısa ama anlamlı metinleri de kabul edebilmek için düşük tutulabilir.
    """
    docs, debug_rows = [], []
    ok, fail = 0, 0

    for it in picked_items:
        f_url, f_code, f_html, amp_u, amp_c, amp_h = resolve_and_fetch_with_amp(it["link"], timeout=fetch_timeout)

        # Hangi HTML daha doluysa onu kullan
        use_url, use_code, use_html = (f_url, f_code, f_html)
        if amp_h and len(amp_h) > len(f_html or ""):
            use_url, use_code, use_html = (amp_u, amp_c, amp_h)

        text = extract_main_text_robust(use_html)
        clen = len(text or "")

        debug_rows.append({
            "original_link": it["link"],
            "final_url": use_url,
            "http_code": use_code,
            "chars_extracted": clen
        })

        if text and clen >= min_accept_len:
            docs.append({
                "url": use_url,
                "title": it["title"],
                "published": it["published"],
                "text": text
            })
            ok += 1
        else:
            # Çok kısa ama anlamlı olabilecekleri de “son şans” olarak kabul et
            if text and clen >= max(60, int(min_accept_len*0.5)):
                docs.append({
                    "url": use_url,
                    "title": it["title"],
                    "published": it["published"],
                    "text": text
                })
                ok += 1
            else:
                fail += 1

        time.sleep(0.30)  # kibar bekleme

    return docs, ok, fail, pd.DataFrame(debug_rows)

# =========================
# GROK: TESİS ADI ÇIKARIMI
# =========================
SYSTEM_PROMPT = """
Sigorta amaçlı bilgi çıkarımı yapıyorsun.
Aşağıda her bir haber için title, url ve article_text (haber gövdesi) verilecek.
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
    compact = []
    for d in docs:
        compact.append({
            "url": d["url"],
            "title": unidecode((d["title"] or ""))[:220],
            "published": d["published"].strftime("%Y-%m-%d %H:%M") if isinstance(d["published"], datetime) else "",
            "article_text": unidecode((d["text"] or ""))[:2000]  # token tasarrufu
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
    max_links = st.slider("Toplanacak haber sayısı", 5, 80, 30, step=5)
    fetch_timeout = st.slider("HTML indirme zaman aşımı (sn)", 6, 20, 16)
    text_minlen = st.slider("Gerekli minimum metin uzunluğu", 80, 1500, 120, step=20)

    model_name = st.selectbox("Grok Modeli", [DEFAULT_MODEL, "grok-3", "grok-4"], index=0)
    batch_size = st.slider("Grok batch boyutu", 3, 20, 8, step=1)

# Tek URL test (debug)
with st.sidebar:
    st.markdown("---")
    st.markdown("**Tek URL test (debug)**")
    test_url = st.text_input("URL gir (isteğe bağlı)")
    if st.button("URL'yi test et"):
        u1,u1c,h1,u2,u2c,h2 = resolve_and_fetch_with_amp(test_url, timeout=fetch_timeout)
        html_to_use = h2 if h2 and len(h2) > len(h1 or "") else h1
        text = extract_main_text_robust(html_to_use)
        st.write("Final URL:", u1)
        st.write("HTTP:", u1c)
        st.write("Karakter:", len(text or ""))
        st.code((text or "")[:1200])

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
        st.warning("Seçilen aralık/filtre ile uygun link bulunamadı. 'Sadece yerel' filtresini kapatıp yeniden deneyin.")
        st.stop()

    # HTML getir + metin çıkar
    docs, ok, fail, debug_df = prepare_docs_for_grok(
        picked, fetch_timeout=fetch_timeout, min_accept_len=int(text_minlen)
    )
    st.info(f"Metin çıkarımı: başarı={ok}, başarısız={fail}. Grok'a {len(docs)} makale gönderilecek.")

    st.subheader("🧪 Debug – İndirilen Sayfalar")
    st.dataframe(debug_df, use_container_width=True)

    if not docs:
        st.warning("Yeterli metin çıkarılamadı. 'Sadece yerel' filtresini kapatın, minimum metni 80–120 aralığına çekin, "
                   "veya zaman aşımını 18–20 sn yapın.")
        st.stop()

    # Grok batch
    results = []
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    for chunk in chunks(docs, batch_size):
        with st.spinner(f"Grok çıkarım yapıyor... ({len(chunk)} makale)"):
            out = grok_extract_from_articles(model_name, chunk)
            results.extend(out)
        time.sleep(0.8)

    if not results:
        st.warning("Grok, sağlanan metinlerden tesis adı çıkaramadı. Parametreleri ayarlayıp tekrar deneyin.")
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

    st.success("Tamam. Sonraki adımda bu sonuçları harita/PD-BI analizine besleyebiliriz.")
else:
    st.info("Parametreleri seçip 'Tesis Adlarını Çıkar' butonuna basın. Bu adım yalnızca TESİS ADI tespiti yapar (Grok ile).")
