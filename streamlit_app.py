# ==============================================================================
#  Pragmatik MVP (v39.0): Hibrit Metin Çekme (Önce RSS Özeti, Sonra Web)
# ==============================================================================
import streamlit as st
import pandas as pd
import requests
import feedparser
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
from urllib.parse import quote, urlparse
import time

# Metin Çıkarma Kütüphaneleri (Sadece gerekirse kullanılacak)
import trafilatura
from bs4 import BeautifulSoup
import readability

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API BAĞLANTILARI
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Pragmatik Hasar Motoru")
st.title("🛰️ Akıllı Hasar Analiz Motoru (Hibrit Mod)")

grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. YARDIMCI FONKSİYONLAR
# ------------------------------------------------------------------------------

# -- Adım 1: En Güncel Olay Adayını ve ÖZETİNİ Bulma --
@st.cache_data(ttl=600)
def get_latest_event_candidate_with_summary():
    # ... (Bu fonksiyonun içi bir önceki versiyonla aynı kalabilir, sadece dönüş değerini güncelleyeceğiz)
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return None, "Google News RSS akışı bu kriterler için boş sonuç döndürdü."
        
        entries = sorted(feed.entries, key=lambda e: getattr(e, "published_parsed", time.gmtime(0)), reverse=True)
        if entries:
            entry = entries[0]
            # HTML etiketlerini temizlemek için basit bir regex
            summary_text = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            candidate = {
                "headline": entry.title.split(" - ")[0], 
                "url": entry.link,
                "summary": summary_text # ÖNEMLİ: Artık özeti de alıyoruz
            }
            return candidate, "En güncel olay adayı bulundu."
        return None, "RSS akışında haber bulundu ancak işlenemedi."
    except Exception as e:
        return None, f"RSS erişim hatası: {e}"

# -- Adım 2 (Gerekirse): Haber Metnini Web'den Çekme --
@st.cache_data(ttl=3600)
def fetch_full_text_from_url(url: str) -> str:
    try:
        # Bu fonksiyon en son çalışan, trafilatura tabanlı versiyonumuz
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        html_doc = resp.text
        extracted = trafilatura.extract(html_doc, include_comments=False, include_tables=False)
        if extracted and len(extracted.strip()) > 200:
            return extracted.strip()
        return ""
    except Exception:
        return ""

# -- Adım 3: AI Analiz Zinciri --
# Bu fonksiyon artık hangi metni (özet veya tam metin) alıyorsa onunla çalışacak
def run_ai_analysis_pipeline(_client, text_to_analyze):
    # Bu fonksiyonun iç mantığı değişmedi, sadece girdisi esnek hale geldi
    # Aşama A: İpuçlarını Çıkar
    clues_prompt = f"GÖREV: Aşağıdaki haber metnini oku ve X'te arama yapmak için kullanılabilecek en spesifik ipuçlarını çıkar. Çıktıyı SADECE JSON formatında ver.\nHABER METNİ: \"{text_to_analyze[:8000]}\"\n\nJSON YAPISI: {{\"en_spesifik_konum\": \"...\", \"tesis_tipi\": \"...\", \"olay_detaylari\": \"...\"}}"
    clues_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": clues_prompt}], max_tokens=1024, temperature=0.0)
    clues_match = re.search(r'\{.*\}', clues_response.choices[0].message.content, re.DOTALL)
    clues = json.loads(clues_match.group(0)) if clues_match else {}
    if not clues: return None, "Metinden ipucu çıkarılamadı."

    # Aşama B ve C... (kodun geri kalanı aynı)
    x_prompt = f"Sen bir OSINT uzmanısın... İPUÇLARI: {clues}..." # Kısaltıldı
    x_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": x_prompt}], max_tokens=2048, temperature=0.0)
    company_match = re.search(r'\{.*\}', x_response.choices[0].message.content, re.DOTALL)
    company_info = json.loads(company_match.group(0)) if company_match else {}
    if not company_info or company_info.get('tesis_adi') == 'Teyit Edilemedi': return None, f"Tesis adı X simülasyonu ile teyit edilemedi. AI Kanıtı: {company_info.get('kanit', 'N/A')}"

    report_prompt = f"Sen elit bir sigorta risk analistisin... BİLGİLER: {company_info} METİN: \"{text_to_analyze[:8000]}\"..." # Kısaltıldı
    report_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": report_prompt}], max_tokens=4096, temperature=0.1)
    report_match = re.search(r'\{.*\}', report_response.choices[0].message.content, re.DOTALL)
    final_data = json.loads(report_match.group(0)) if report_match else {}
    final_data.update(company_info)
    return final_data, "Rapor başarıyla oluşturuldu."

# -- Harita Fonksiyonu (Değişiklik yok) --
@st.cache_data
def find_neighboring_facilities(api_key, lat, lon):
    # ... (kodun içi aynı)
    pass
# ------------------------------------------------------------------------------
# 4. STREAMLIT ARAYÜZÜ VE YENİ HİBRİT AKIŞ
# ------------------------------------------------------------------------------
st.sidebar.header("Kontrol Paneli")
if st.sidebar.button("🚀 En Son Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    if not client or not google_api_key:
        st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.status("Analiz süreci yürütülüyor...", expanded=True) as status:
        # Adım 1: Adayı ve özetini al
        status.write("Aşama 1: En güncel olay adayı haber kaynaklarından taranıyor...")
        event_candidate, msg = get_latest_event_candidate_with_summary()
        if not event_candidate:
            status.update(label=f"Hata: {msg}", state="error"); st.stop()
        
        st.session_state.event_candidate = event_candidate
        text_for_analysis = None
        
        # Adım 2: Hibrit Metin Seçimi
        rss_summary = event_candidate.get("summary", "")
        if len(rss_summary) > 200:
            status.write("Aşama 2: Yeterli RSS özeti bulundu, doğrudan kullanılıyor...")
            text_for_analysis = rss_summary
        else:
            status.write("Aşama 2: RSS özeti yetersiz, haberin tam metni web'den çekiliyor...")
            full_text = fetch_full_text_from_url(event_candidate['url'])
            if not full_text:
                status.update(label="Hata: Haber metni web sitesinden de çekilemedi. Site korumalı olabilir.", state="error"); st.stop()
            text_for_analysis = full_text

        # Adım 3: Seçilen metinle analizi çalıştır
        status.write("Aşama 3: AI Analiz Zinciri çalıştırılıyor...")
        report_data, msg = run_ai_analysis_pipeline(client, text_for_analysis)
        if not report_data:
            status.update(label=f"Hata: {msg}", state="error"); st.stop()
        
        # ... (Adım 4 ve Rapor Gösterme, önceki versiyonla tamamen aynı)
        status.write("Aşama 4: Rapor coğrafi verilerle zenginleştiriliyor...")
        # ... (Haritalama ve raporu session_state'e kaydetme kodları)
        st.session_state.report = report_data
        status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)

# Raporu Görüntüleme Alanı (Değişiklik yok)
if 'report' in st.session_state and st.session_state.report:
    # ... (önceki versiyondaki rapor gösterme kodunun tamamı)
    pass
