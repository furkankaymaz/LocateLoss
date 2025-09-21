# -*- coding: utf-8 -*-
import os
import re
import json
import time
import requests
import feedparser
import pandas as pd
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateparser
from unidecode import unidecode
from rapidfuzz import fuzz, process
import streamlit as st
from openai import OpenAI
import folium
from streamlit_folium import folium_static

# =========================
# AYARLAR
# =========================
st.set_page_config(page_title="Hasar İstihbarat (TR)", layout="wide")
st.title("🚨 Endüstriyel Hasar İstihbarat – Türkiye (Grok + RSS)")

# Ortam değişkeni: GROK_API_KEY zorunlu
GROK_API_KEY = os.getenv("GROK_API_KEY")
DEFAULT_MODEL = "grok-3"  # erişiminize göre "grok-4" veya "grok-4-fast-reasoning" da seçebilirsiniz
BASE_URL = "https://api.x.ai/v1"

if not GROK_API_KEY:
    st.error("GROK_API_KEY bulunamadı. Lütfen ortam değişkeni olarak ekleyin.")
    st.stop()

client = OpenAI(api_key=GROK_API_KEY, base_url=BASE_URL)

# =========================
# YARDIMCI FONKSİYONLAR
# =========================
def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unidecode(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def truncate(s: str, n: int = 280) -> str:
    if not s:
        return s
    return s if len(s) <= n else s[: n - 3] + "..."

def google_news_rss_query(keywords: str, days: int = 30) -> str:
    """
    Google News RSS: Türkçe sonuçlar, TR odaklı.
    'when:Xd' ifadesiyle zaman kısıtı veriyoruz. site:tr ile yerel kaynakları öne çıkarıyoruz.
    """
    q = requests.utils.quote(f'({keywords}) site:tr when:{days}d')
    return f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"

def fetch_rss_articles(keyword_list, days_back=30, max_per_keyword=20):
    """
    Birden fazla anahtar kelime için Google News RSS’den haber çeker.
    Çıktı: list[dict] => {title, link, published, source, summary}
    """
    all_items = []
    for kw in keyword_list:
        url = google_news_rss_query(kw, days_back)
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_per_keyword]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = entry.get("published", "") or entry.get("updated", "")
            try:
                pub_dt = dateparser.parse(published)
            except Exception:
                pub_dt = None
            source = entry.get("source", {}).get("title") or entry.get("author", "") or "RSS"

            all_items.append(
                {
                    "keyword": kw,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": pub_dt,
                    "source": source,
                }
            )
        # RSS limitleri nazik davranır; hızlı istekleri bölmek iyi olur
        time.sleep(0.6)
    return all_items

def dedupe_articles(items):
    """
    Link ve başlığa göre kaba deduplikasyon.
    """
    seen_links = set()
    out = []
    for it in items:
        link = it["link"]
        title = normalize_text(it["title"]).lower()
        if (link in seen_links) or any(
            fuzz.token_sort_ratio(title, normalize_text(x["title"]).lower()) >= 93 for x in out
        ):
            continue
        seen_links.add(link)
        out.append(it)
    return out

def filter_by_date(items, start, end):
    out = []
    for it in items:
        dt = it.get("published")
        if not isinstance(dt, datetime):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if start <= dt <= end:
            out.append(it)
    return out

def load_reference_facilities(uploaded_file) -> pd.DataFrame | None:
    """
    Kullanıcı isterse CSV ile bir tesis referans listesi yükleyebilir.
    Beklenen kolonlar (esnek): ['tesis_adi', 'sehir', 'ilce', 'adres']
    """
    if uploaded_file is None:
        return None
    try:
        df = pd.read_csv(uploaded_file)
        # kolon isimlerini normalize et
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except Exception as e:
        st.warning(f"Referans dosyası okunamadı: {e}")
        return None

def fuzzy_match_facility(name: str, ref_df: pd.DataFrame, threshold: int = 90):
    """
    Referans listesi varsa ad eşleştirme yapar; yoksa None döner.
    """
    if ref_df is None or "tesis_adi" not in ref_df.columns:
        return None
    choices = ref_df["tesis_adi"].astype(str).tolist()
    best = process.extractOne(name, choices, scorer=fuzz.WRatio)
    if best and best[1] >= threshold:
        matched_name = best[0]
        row = ref_df[ref_df["tesis_adi"] == matched_name].iloc[0].to_dict()
        row["match_score"] = int(best[1])
        return row
    return None

def call_grok_structured(model: str, items: list, start_date: datetime, end_date: datetime, damage_scope: str):
    """
    RSS'ten gelen linkleri Grok’a verip SADECE bu kaynaklara dayanarak
    olay çıkarımı yaptırır. Çıkış: JSON array (olaylar).
    """
    system_prompt = f"""
Sen bir sigorta uzmanısın. Aşağıda verilen TÜM kaynak linkleri ve özetler DIŞINA ÇIKMADAN,
{start_date.strftime('%d %B %Y')} - {end_date.strftime('%d %B %Y')} tarihleri arasında
Türkiye'de gerçekleşen '{damage_scope}' kapsamındaki endüstriyel hasarları tespit et.
Uydurma yapma, kaynakta yoksa 'Teyit Edilemedi' de.

Her olay için JSON nesnesi üret:
[
  {{
    "olay_tarihi": "YYYY-MM-DD",
    "sehir": "...",
    "ilce": "...",
    "adres_detay": "...",
    "tesis_adi": "... | 'Teyit Edilemedi'",
    "olay_tipi": "yangın|patlama|sızıntı|diğer",
    "detay": "kısa özet",
    "sigorta_degeri": "Yüksek|Orta|Düşük",
    "tahmini_kayip": "metin (rakam varsa)",
    "latitude": null,   // kaynakta yoksa null bırak
    "longitude": null,  // kaynakta yoksa null bırak
    "kaynaklar": ["link1", "link2", ...],
    "dogruluk_notu": "Neden bu tesisi seçtin / neden teyit edilemedi?"
  }},
  ...
]

Kurallar:
- Kaynağa dayanmayan bilgi ekleme.
- Tesis adı net değilse 'Teyit Edilemedi'.
- Kaynak sayısı < 1 ise olay üretme.
- Zaman dışındaki haberleri dahil etme.
- Sadece Türkiye sınırındaki olayları listele.
- Yanıtın SADECE ham JSON dizi olsun.
"""

    # Items'ı kompakt bir listeye çevir
    compact = []
    for it in items:
        compact.append(
            {
                "title": truncate(it["title"], 180),
                "link": it["link"],
                "published": it["published"].strftime("%Y-%m-%d %H:%M") if isinstance(it["published"], datetime) else "",
                "summary": truncate(re.sub("<.*?>", "", it.get("summary", "") or ""), 500),
                "source": it.get("source", "RSS"),
            }
        )

    user_payload = {
        "damage_scope": damage_scope,
        "time_window": [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")],
        "items": compact[:60]  # güvenli sınır
    }

    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=3000,
        temperature=0.0  # kaynağa sadakat için düşük
    )
    content = (resp.choices[0].message.content or "").strip()

    # Sadece JSON dizi bekliyoruz
    m = re.search(r"\[.*\]\s*$", content, re.DOTALL)
    if not m:
        return []

    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

# =========================
# SIDEBAR – Parametreler
# =========================
with st.sidebar:
    st.header("Sorgu Ayarları")
    today = datetime.now(timezone.utc)
    end_date = st.date_input("Bitiş Tarihi", value=today.date())
    days_back = st.slider("Geri Gün Sayısı", 1, 90, 30)
    start_date = datetime.combine(end_date - timedelta(days=days_back), datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    damage_type = st.selectbox("Hasar Tipi", ["Endüstriyel ve Enerji", "Sadece Endüstriyel"])

    st.markdown("**Anahtar Kelime Grupları (TR)**")
    default_keywords = [
        "fabrika yangın",
        "tesis yangın",
        "sanayi yangını",
        "OSB yangın",
        "patlama fabrika",
        "kimyasal sızıntı",
        "rafineri yangın",
        "enerji santrali yangın",
        "trafo patlaması",
        "üretim durdu",
    ]
    kw_text = st.text_area("Kelime listesi (satır satır)", value="\n".join(default_keywords), height=180)

    uploaded_ref = st.file_uploader("Opsiyonel: Tesis referans listesi (CSV)", type=["csv"])

    model_name = st.selectbox("Grok Modeli", [DEFAULT_MODEL, "grok-4-fast-reasoning", "grok-4"], index=0)

    run_btn = st.button("Raporu Oluştur")

st.markdown("---")

# =========================
# ÇALIŞTIR
# =========================
if run_btn:
    keywords = [k.strip() for k in kw_text.splitlines() if k.strip()]
    with st.spinner("RSS kaynakları taranıyor..."):
        items = fetch_rss_articles(keywords, days_back=days_back, max_per_keyword=20)
        items = filter_by_date(items, start_date, end_dt)
        items = dedupe_articles(items)
        items = sorted(items, key=lambda x: x["published"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)

    st.success(f"RSS kaynaklarından {len(items)} aday haber çekildi.")
    if not items:
        st.stop()

    with st.spinner("Grok ile olay çıkarımı yapılıyor (kaynak bazlı, uydurma yok)..."):
        events = call_grok_structured(model_name, items, start_date, end_dt, damage_type)

    if not events:
        st.warning("Kaynaklara dayalı bir olay çıkarılamadı.")
        st.stop()

    # JSON -> DataFrame
    df = pd.DataFrame(events)

    # Tesis referans eşleştirme (opsiyonel)
    ref_df = load_reference_facilities(uploaded_ref)
    match_cols = ["ref_tesis_adi", "ref_sehir", "ref_ilce", "ref_adres", "match_score"]
    for c in match_cols:
        df[c] = None

    if ref_df is not None and "tesis_adi" in ref_df.columns:
        for i, row in df.iterrows():
            name = row.get("tesis_adi") or ""
            if name and name != "Teyit Edilemedi":
                m = fuzzy_match_facility(name, ref_df, threshold=90)
                if m:
                    df.at[i, "ref_tesis_adi"] = m.get("tesis_adi")
                    df.at[i, "ref_sehir"] = m.get("sehir")
                    df.at[i, "ref_ilce"] = m.get("ilce")
                    df.at[i, "ref_adres"] = m.get("adres")
                    df.at[i, "match_score"] = m.get("match_score")

    # Görüntüleme
    st.subheader("📋 Olay Listesi (Kaynak Tabanlı)")
    show_cols = [
        "olay_tarihi", "sehir", "ilce", "tesis_adi", "olay_tipi",
        "sigorta_degeri", "tahmini_kayip", "dogruluk_notu"
    ]
    for c in show_cols:
        if c not in df.columns:
            df[c] = None

    st.dataframe(df[show_cols], use_container_width=True)

    # Kaynak linkleri
    st.subheader("🔗 Kaynaklar")
    for idx, row in df.iterrows():
        srcs = row.get("kaynaklar") or []
        srcs = [s for s in srcs if isinstance(s, str)]
        if not srcs:
            continue
        st.markdown(f"**Olay {idx+1}:** {truncate(str(row.get('tesis_adi') or 'Tesis bilinmiyor'), 60)}")
        for s in srcs[:6]:
            st.markdown(f"- {s}")

    # Harita
    st.subheader("🗺️ Harita Görselleştirme")
    try:
        map_df = df.dropna(subset=["latitude", "longitude"]).copy()
        map_df["latitude"] = pd.to_numeric(map_df["latitude"], errors="coerce")
        map_df["longitude"] = pd.to_numeric(map_df["longitude"], errors="coerce")
        map_df = map_df.dropna(subset=["latitude", "longitude"])
        if not map_df.empty:
            center = [map_df["latitude"].mean(), map_df["longitude"].mean()]
            m = folium.Map(location=center, zoom_start=6)
            for _, r in map_df.iterrows():
                popup = f"<b>{r.get('tesis_adi') or 'Tesis?'}</b><br>{r.get('olay_tarihi') or ''}<br>{truncate(r.get('detay') or '', 180)}"
                folium.Marker(
                    [float(r["latitude"]), float(r["longitude"])],
                    popup=folium.Popup(popup, max_width=360),
                    tooltip=r.get("olay_tipi") or "Olay"
                ).add_to(m)
            folium_static(m, width=1100, height=600)
        else:
            st.info("Konum verisi bulunamadı veya kaynaklarda yer almıyor.")
    except Exception as e:
        st.warning(f"Harita oluşturulurken hata: {e}")

    # Rapor çıktısı (Markdown)
    st.subheader("📝 Rapor (Markdown)")
    # Markdown raporu Grok ile biçimlendir (sadece veriyi kullanarak)
    try:
        report_messages = [
            {
                "role": "system",
                "content": f"""
Sen bir sigorta uzmanısın. Aşağıdaki OLAY VERİLERİNE sadık kalarak,
kronolojik bir Markdown raporu üret. Olaylar kaynak tabanlıdır; uydurma yapma.
Her olay için: Tarih, Yer, Tesis Adı (Teyitli/Teyit Edilemedi), Detay, Sigortacılık Açısından Değer ve Tahmini Kayıp.
Sonunda: Toplam kayıp tahmini (varsa) ve son dakika notu.
"""
            },
            {"role": "user", "content": df.to_json(orient="records", force_ascii=False)}
        ]
        r = client.chat.completions.create(
            model=model_name, messages=report_messages, max_tokens=2000, temperature=0.1
        )
        md = r.choices[0].message.content
        st.markdown(md)
    except Exception as e:
        st.warning(f"Rapor üretiminde hata: {e}")

else:
    st.info("Soldan parametreleri seçip 'Raporu Oluştur' butonuna basın. İsterseniz tesis referans CSV’si yükleyip eşleştirme yapabilirsiniz.")
    with st.expander("Nasıl çalışır?"):
        st.markdown(
            """
- **RSS Toplama (deterministik):** Google News RSS üzerinden TR haberleri çekilir (site:tr).
- **Kaynak Bazlı Çıkarım (Grok):** Haber linkleri ve özetleri Grok’a verilir; **sadece bu kaynaklara dayanarak** olay JSON’u üretilir.
- **Teyit İlkesi:** Tesis adı net değilse **'Teyit Edilemedi'**. Uydurma yok.
- **Opsiyonel Referans:** CSV tesis listesi yüklerseniz **fuzzy match** ile teyit skoru hesaplanır.
- **Harita & Rapor:** Koordinatlar varsa harita, ardından Markdown raporu oluşturulur.
"""
        )
