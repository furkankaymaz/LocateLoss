# ==============================================================================
#  Sadeleştirilmiş MVP (v38.0): Tek Olay, Tam Analiz (Veritabansız)
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

# Metin Çıkarma Kütüphaneleri
import trafilatura
from bs4 import BeautifulSoup
import readability

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API BAĞLANTILARI
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Tek Olay Analiz Motoru")
st.title("🛰️ Akıllı Hasar Analiz Motoru (Tek Olay Modu)")

# --- API Bağlantıları (Streamlit Secrets'ten) ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. YARDIMCI FONKSİYONLAR (METİN ÇEKME, AI ZİNCİRİ, HARİTA)
# ------------------------------------------------------------------------------

# -- Adım 1: En Güncel Olay Adayını Bulma --
@st.cache_data(ttl=600)
def get_latest_event_candidate():
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return None, "Google News RSS akışı bu kriterler için boş sonuç döndürdü."
        
        # En yeniden eskiye doğru sırala ve ilk uygun olanı al
        entries = sorted(feed.entries, key=lambda e: getattr(e, "published_parsed", time.gmtime(0)), reverse=True)
        if entries:
            entry = entries[0]
            return {"headline": entry.title.split(" - ")[0], "url": entry.link}, "En güncel olay adayı bulundu."
        return None, "RSS akışında haber bulundu ancak işlenemedi."
    except Exception as e:
        return None, f"RSS erişim hatası: {e}"

# -- Adım 2: Haber Metnini Çekme --
@st.cache_data(ttl=3600)
def fetch_article_text(url: str) -> str:
    try:
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
def run_ai_analysis_pipeline(_client, full_text):
    # Aşama A: İpuçlarını Çıkar
    clues_prompt = f"GÖREV: Aşağıdaki haber metnini oku ve X'te arama yapmak için kullanılabilecek en spesifik ipuçlarını çıkar. Çıktıyı SADECE JSON formatında ver.\nHABER METNİ: \"{full_text[:8000]}\"\n\nJSON YAPISI: {{\"en_spesifik_konum\": \"...\", \"tesis_tipi\": \"...\", \"olay_detaylari\": \"...\"}}"
    clues_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": clues_prompt}], max_tokens=1024, temperature=0.0)
    clues_match = re.search(r'\{.*\}', clues_response.choices[0].message.content, re.DOTALL)
    clues = json.loads(clues_match.group(0)) if clues_match else {}
    if not clues: return None, "Metinden ipucu çıkarılamadı."

    # Aşama B: X Simülasyonu ile Tesis Adını Bul
    x_prompt = f"Sen bir OSINT uzmanısın. Görevin, sana verilen ipuçlarını kullanarak X (Twitter) üzerinde nokta atışı bir arama simülasyonu yapmak ve olayın yaşandığı tesisin ticari unvanını teyit etmektir. ASLA TAHMİN YÜRÜTME.\nİPUÇLARI: {clues}\n\nÇIKTI FORMATI (SADECE JSON): {{\"tesis_adi\": \"Yüksek kesinlikle bulunan isim VEYA 'Teyit Edilemedi'\", \"kanit\": \"İsmi nasıl bulduğunun açıklaması.\"}}"
    x_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": x_prompt}], max_tokens=2048, temperature=0.0)
    company_match = re.search(r'\{.*\}', x_response.choices[0].message.content, re.DOTALL)
    company_info = json.loads(company_match.group(0)) if company_match else {}
    if not company_info or company_info.get('tesis_adi') == 'Teyit Edilemedi': return None, f"Tesis adı X simülasyonu ile teyit edilemedi. AI Kanıtı: {company_info.get('kanit', 'N/A')}"

    # Aşama C: Nihai Raporu Oluştur
    report_prompt = f"Sen elit bir sigorta risk analistisin. Bilgiler şunlar:\n- TEYİT EDİLMİŞ TESİS BİLGİSİ: {company_info}\n- OLAYIN HABER METNİ: \"{full_text[:8000]}\"\n\nGÖREVİN: Bu bilgileri kullanarak, aşağıdaki tüm anahtarları dolduran nihai ve detaylı JSON raporunu oluştur.\n\nJSON YAPISI: \"sehir_ilce\", \"tahmini_koordinat\": {{\"lat\": \"...\", \"lon\": \"...\"}}, \"maddi_hasar_fiziksel_boyut\", \"is_durmasi_kar_kaybi\", \"hasarin_nedeni\", \"yapilan_mudahale\", \"guncel_durum\", \"cevreye_etki\", \"gorsel_url\""
    report_response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": report_prompt}], max_tokens=4096, temperature=0.1)
    report_match = re.search(r'\{.*\}', report_response.choices[0].message.content, re.DOTALL)
    final_data = json.loads(report_match.group(0)) if report_match else {}
    final_data.update(company_info)
    return final_data, "Rapor başarıyla oluşturuldu."


# -- Adım 4: Harita Fonksiyonu --
@st.cache_data
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=1000&type=establishment&keyword=fabrika|depo|sanayi|tesis&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "adres": p.get('vicinity'), "lat": p.get('geometry',{}).get('location',{}).get('lat'),"lng": p.get('geometry',{}).get('location',{}).get('lng')} for p in results[:10]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 4. STREAMLIT ARAYÜZÜ VE ANA AKIŞ
# ------------------------------------------------------------------------------
st.sidebar.header("Kontrol Paneli")
if st.sidebar.button("🚀 En Son Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    if not client or not google_api_key:
        st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.status("Analiz süreci yürütülüyor...", expanded=True) as status:
        # Adım 1
        status.write("Aşama 1: En güncel olay adayı haber kaynaklarından taranıyor...")
        event_candidate, msg = get_latest_event_candidate()
        if not event_candidate:
            status.update(label=f"Hata: {msg}", state="error"); st.stop()
        st.session_state.event_candidate = event_candidate
        
        # Adım 2
        status.write(f"Aşama 2: '{event_candidate['headline']}' haberinin tam metni çekiliyor...")
        full_text = fetch_article_text(event_candidate['url'])
        if not full_text:
            status.update(label="Hata: Haber metni çekilemedi.", state="error"); st.stop()

        # Adım 3
        status.write("Aşama 3: AI Analiz Zinciri çalıştırılıyor (İpucu -> X Sim -> Rapor)...")
        report_data, msg = run_ai_analysis_pipeline(client, full_text)
        if not report_data:
            status.update(label=f"Hata: {msg}", state="error"); st.stop()
        
        # Adım 4
        status.write("Aşama 4: Rapor coğrafi verilerle zenginleştiriliyor...")
        coords = report_data.get('tahmini_koordinat', {})
        lat, lon = coords.get('lat'), coords.get('lon')
        if lat and lon:
           report_data['komsu_tesisler'] = find_neighboring_facilities(google_api_key, lat, lon)
        
        st.session_state.report = report_data
        status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)

# Raporu Görüntüleme Alanı
if 'report' in st.session_state and st.session_state.report:
    report = st.session_state.report
    event_candidate = st.session_state.event_candidate
    
    st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
    st.caption(f"Kaynak Haber: [{event_candidate['headline']}]({event_candidate['url']})")
    st.info(f"**Kanıt:** *\"{report.get('kanit', 'Kanıt bulunamadı.')}\"*")
    
    if report.get('gorsel_url') and 'http' in report.get('gorsel_url'):
        st.image(report['gorsel_url'], use_column_width=True)

    with st.expander("Detaylı Rapor", expanded=True):
        st.subheader("Hasar ve Olay Detayları")
        col1, col2 = st.columns(2)
        with col1:
            st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
        with col2:
            st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
        
        st.subheader("Finansal Etki Tahmini")
        col3, col4 = st.columns(2)
        with col3: st.metric(label="Maddi Hasar", value=report.get('maddi_hasar_tahmini', 'Tespit Edilemedi'))
        with col4: st.metric(label="İş Durması / Kar Kaybı", value=report.get('kar_kaybi_tahmini', 'Tespit Edilemedi'))
        
    with st.expander("Harita ve Çevre Analizi", expanded=True):
        lat, lon = report.get('tahmini_koordinat', {}).get('lat'), report.get('tahmini_koordinat', {}).get('lon')
        if lat and lon:
            try:
                m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                neighbors = report.get('komsu_tesisler', [])
                for neighbor in neighbors:
                    if neighbor.get('lat') and neighbor.get('lng'):
                        folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b>", icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                folium_static(m, height=450)
                st.write("Komşu Tesisler (1km Yakınlık)")
                st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])
            except (ValueError, TypeError): st.warning("Harita çizilemiyor.")
        else:
            st.info("Rapor, harita çizimi için koordinat bilgisi içermiyor.")
