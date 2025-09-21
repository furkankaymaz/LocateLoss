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

# -------------------------------
# APP CONFIG
# -------------------------------
st.set_page_config(page_title="Tesis Adı Çıkarımı (Grok)", layout="wide")
st.title("🏭 Tesis Adı Çıkarımı – Grok Odaklı (Yerel + X doğrulama yönlendirmeli)")

XAI_API_KEY = os.getenv("XAI_API_KEY")
if not XAI_API_KEY:
    st.error("XAI_API_KEY ortam değişkeni tanımlı değil.")
    st.stop()

client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")

DEFAULT_MODEL = "grok-3"  # erişiminize göre "grok-4" veya "grok-4-fast-reasoning" seçebilirsiniz
LOCAL_HINTS = [
    ".bel.tr",".gov.tr",".edu.tr",".k12.tr",".osb",".osb.org",".org.tr",
    "haber","sondakika","yerel","manset","gazete","kent","kenthaber","medya"
]

TR_CITIES = [
    "Adana","Adıyaman","Afyonkarahisar","Ağrı","Aksaray","Amasya","Ankara","Antalya","Ardahan","Artvin",
    "Aydın","Balıkesir","Bartın","Batman","Bayburt","Bilecik","Bingöl","Bitlis","Bolu","Burdur",
    "Bursa","Çanakkale","Çankırı","Çorum","Denizli","Diyarbakır","Düzce","Edirne","Elazığ","Erzincan",
    "Erzurum","Eskişehir","Gaziantep","Giresun","Gümüşhane","Hakkâri","Hatay","Iğdır","Isparta","İstanbul",
    "İzmir","Kahramanmaraş","Karabük","Karaman","Kars","Kastamonu","Kayseri","Kırıkkale","Kırklareli","Kırşehir",
    "Kilis","Kocaeli","Konya","Kütahya","Malatya","Manisa","Mardin","Mersin","Muğla","Muş",
    "Nevşehir","Niğde","Ordu","Osmaniye","Rize","Sakarya","Samsun","Siirt","Sinop","Sivas",
    "Şanlıurfa","Şırnak","Tekirdağ","Tokat","Trabzon","Tunceli","Uşak","Van","Yalova","Yozgat","Zonguldak"
]
CITY_RX = re.compile(r"\b(" + "|".join([re.escape(c) for c in TR_CITIES]) + r")\b", re.IGNORECASE)

def norm(s: str) -> str:
    if not s: return ""
    s = unidecode(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# -------------------------------
# RSS FETCH (deterministik)
# -------------------------------
def google_news_rss_query(keywords: str, days: int = 7) -> str:
    q = requests.utils.quote(f'({keywords}) when:{days}d')
    # TR odaklı; ulusal kaynaklar gelebilir ama sonra filtreleyeceğiz
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
        time.sleep(0.4)  # nazik
    return items

def domain_score(u: str) -> int:
    try:
        d = urlparse(u).netloc.lower()
    except Exception:
        return 0
    # Yerel ipucu içeren domainleri öne çek
    score = 0
    for hint in LOCAL_HINTS:
        if hint in d:
            score += 2
    # büyük ulusal domainleri biraz kırp (ajanslar yerine yerel kaynak istiyoruz)
    if any(x in d for x in ["ntv","cnnturk","hurriyet","sozcu","sabah","aa.com.tr","dha.com.tr"]):
        score -= 1
    return score

def rank_and_pick(items, start_dt, end_dt, limit=30, only_local=True):
    # tarih aralığı
    items = [it for it in items if isinstance(it["published"], datetime) and start_dt <= it["published"] <= end_dt]
    # skorla
    for it in items:
        it["score"] = domain_score(it["link"])
    if only_local:
        items = [it for it in items if it["score"] >= 1]
    # taze + puanlı sırala
    items = sorted(items, key=lambda x: (x["score"], x["published"]), reverse=True)
    return items[:limit]

# -------------------------------
# GROK: TESIS ADI ÇIKARIMI
# -------------------------------
SCHEMA_EXAMPLE = [
  {
    "olay_tarihi": "2025-09-18",
    "sehir": "Kayseri",
    "ilce": "Melikgazi",
    "tesis_adi": "Örnek Tekstil A.Ş. Fabrikası",
    "tesis_ad_teyit": "TEYITLI | TAHMIN | TEYIT_EDILEMEDI",
    "kanit_linkleri": ["https://yerelgazete.com.tr/...", "https://x.com/..."],
    "aciklama": "Yerel haberde tesisin unvanı açıkça geçiyor. X hesabında itfaiye teyidi var.",
    "guven_skoru": 0.92
  }
]

SYSTEM_PROMPT = """
Sen bir sigorta uzmanısın ve canlı bilgiye erişebilen bir araştırmacı gibi davranacaksın.
Aşağıda verilen HABER LİSTESİ, Türkiye'deki endüstriyel/sanayi olaylarına dair linklerden oluşur.
Görevin: her linki **mümkünse yerel haber ve X paylaşımları ile teyit ederek** olay bazında TESİS ADI'nı çıkarmak.
Kurallar:
- Tesis adı net ve açık unvanla geçiyorsa "tesis_ad_teyit" = TEYITLI.
- Sadece metinden tahmin ediliyorsa "TAHMIN".
- Bulunamadıysa "TEYIT_EDILEMEDI".
- Mümkünse en az 2 **kanıt_linki** ver (yerel haber + X postu/itfaiye/valilik).
- Sadece Türkiye içindeki olaylar, son günlerdeki haberler.
- Yanıt SADECE JSON dizi olsun; başka metin yok.
- JSON alanları: olay_tarihi, sehir, ilce, tesis_adi, tesis_ad_teyit, kanit_linkleri, aciklama, guven_skoru.
Dış doğrulama (web/X) yapabiliyorsan yap; yapamıyorsan link içeriğine ve başlığa dayan.
"""

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

@st.cache_data(show_spinner=False, ttl=900)
def grok_extract_facilities(model, batch_items):
    # batch_items: list of dict {title, summary, link, published}
    payload = []
    for it in batch_items:
        payload.append({
            "title": unidecode(re.sub(r"<.*?>","", it["title"] or ""))[:220],
            "summary": unidecode(re.sub(r"<.*?>","", it["summary"] or ""))[:600],
            "link": it["link"],
            "published": it["published"].strftime("%Y-%m-%d %H:%M") if isinstance(it["published"], datetime) else ""
        })
    messages = [
        {"role":"system","content": SYSTEM_PROMPT.strip()},
        {"role":"user","content": json.dumps({"haber_listesi": payload}, ensure_ascii=False)}
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=2200,
        temperature=0.0
    )
    content = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\[.*\]\s*$", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        # şema güvenliği
        out = []
        for d in data:
            out.append({
                "olay_tarihi": d.get("olay_tarihi"),
                "sehir": d.get("sehir"),
                "ilce": d.get("ilce"),
                "tesis_adi": d.get("tesis_adi"),
                "tesis_ad_teyit": d.get("tesis_ad_teyit"),
                "kanit_linkleri": d.get("kanit_linkleri", []),
                "aciklama": d.get("aciklama"),
                "guven_skoru": d.get("guven_skoru")
            })
        return out
    except Exception:
        return []

# -------------------------------
# UI – Parametreler
# -------------------------------
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
    only_local = st.checkbox("Sadece yerel domainleri Grok'a gönder", value=True)
    max_links = st.slider("Grok'a gönderilecek link sayısı (toplam)", 5, 60, 25, step=5)
    batch_size = st.slider("Batch boyutu (API tasarrufu)", 5, 25, 15, step=5)
    model_name = st.selectbox("Grok Modeli", [DEFAULT_MODEL, "grok-4", "grok-4-fast-reasoning"], index=0)

run = st.button("Tesis Adlarını Çıkar (Grok)")

st.markdown("---")

# -------------------------------
# Çalıştırma
# -------------------------------
if run:
    keywords = [k.strip() for k in kw_text.splitlines() if k.strip()]
    with st.spinner("RSS kaynakları çekiliyor..."):
        raw = fetch_rss(keywords, days_back=days_back, max_per_kw=20)
    st.success(f"RSS'ten {len(raw)} aday haber geldi.")

    picked = rank_and_pick(raw, start_dt, end_dt, limit=max_links, only_local=only_local)
    if not picked:
        st.warning("Seçilen aralık/filtre ile uygun yerel link bulunamadı. 'Sadece yerel' tikini kapatıp tekrar deneyin.")
        st.stop()

    st.info(f"Grok'a gönderilecek link sayısı: {len(picked)} (batch={batch_size})")
    df_src = pd.DataFrame([{
        "published": it["published"],
        "domain": urlparse(it["link"]).netloc if it["link"] else "",
        "title": it["title"], "link": it["link"]
    } for it in picked])
    st.dataframe(df_src, use_container_width=True)

    results = []
    for chunk in chunks(picked, batch_size):
        with st.spinner(f"Grok çıkarım yapıyor... ({len(chunk)} link)"):
            out = grok_extract_facilities(model_name, chunk)
            results.extend(out)
        # nazik bekleme (kotaları zorlamamak için)
        time.sleep(1.0)

    if not results:
        st.warning("Grok, verilen linklerden tesis adı çıkaramadı. Link sayısını artırın veya 'Sadece yerel' filtresini kapatıp yeniden deneyin.")
        st.stop()

    df = pd.DataFrame(results)
    # Kolon düzeni
    for c in ["olay_tarihi","sehir","ilce","tesis_adi","tesis_ad_teyit","guven_skoru","aciklama","kanit_linkleri"]:
        if c not in df.columns:
            df[c] = None

    st.subheader("🔎 Tesis Adı Çıkarımı – Sonuçlar")
    st.dataframe(df[["olay_tarihi","sehir","ilce","tesis_adi","tesis_ad_teyit","guven_skoru","aciklama"]], use_container_width=True)

    st.subheader("🔗 Kanıt Linkleri")
    for i, row in df.iterrows():
        links = row.get("kanit_linkleri") or []
        if links:
            st.markdown(f"**Olay {i+1} – {row.get('tesis_adi') or 'Tesis?'}**")
            for L in links[:6]:
                st.markdown(f"- {L}")

    st.success("Tamam. Sonraki adımda bu sonuçları PD/BI analizi ve haritalama için kullanabiliriz.")
else:
    st.info("Parametreleri seçip 'Tesis Adlarını Çıkar (Grok)' butonuna basın. İlk adımda sadece tesis adı tespiti yapılır; API tüketimi batching ile sınırlıdır.")
