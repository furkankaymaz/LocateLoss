# ==============================================================================
#  NİHAİ KOD (v45.0): İki Aşamalı Protokol ve Gelişmiş Arayüz
# ==============================================================================
import streamlit as st
import pandas as pd
import feedparser
from openai import OpenAI
import json
import re
from urllib.parse import quote
import folium
from streamlit_folium import folium_static
import requests
from rapidfuzz import fuzz
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Akıllı Hasar Tespiti")
st.title("🛰️ Akıllı Endüstriyel Hasar Tespit Motoru")

# --- API Bağlantıları
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. VERİ TOPLAMA VE İŞLEME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_latest_events_from_rss():
    """Google News RSS'ten olayları çeker, sıralar ve daha anlamlı bir liste için hazırlar."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return []
        
        sorted_entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
        
        unique_articles = []
        seen_headlines = []
        
        for entry in sorted_entries:
            headline = entry.title.split(" - ")[0].strip()
            
            if any(fuzz.ratio(headline, seen_headline) > 85 for seen_headline in seen_headlines):
                continue

            summary_text = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            unique_articles.append({
                "headline": headline,
                "snippet": summary_text[:150] + '...' if summary_text else '',
                "full_summary": summary_text,
                "url": entry.link
            })
            seen_headlines.append(headline)

        return unique_articles[:30]
    except Exception as e:
        st.sidebar.error(f"RSS Hata: {e}"); return []

# ------------------------------------------------------------------------------
# 3. İKİ AŞAMALI AI ANALİZ FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def run_detective_ai(_client, headline, summary):
    """Aşama 1: Sadece tesis kimliğini bulmaya odaklanır."""
    prompt = f"""
    Sen, elit bir istihbarat analistisin (Dedektif). Tek görevin, sana verilen ipuçlarından yola çıkarak olayın yaşandığı TESİSİN TİCARİ UNVANINI ve KONUMUNU bulmaktır.
    - İPUÇLARI: Başlık: "{headline}", Özet: "{summary}"
    - DÜŞÜNCE SÜRECİN: Google arama simülasyonu yap. Güvenilir kaynakları (AA, DHA, resmi kurumlar) çapraz kontrol et. Teyit seviyesine göre 1-5 arası Güven Skoru ata.
    - ÇIKTI: Sadece aşağıdaki JSON formatında, başka hiçbir metin olmadan çıktı ver.
    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan.",
      "guven_skoru": "1-5 arası bir sayı.",
      "kanit_zinciri": "Bu isme nasıl ulaştığının ve hangi kaynakların teyit ettiğinin detaylı açıklaması.",
      "sehir_ilce": "Olayın yaşandığı net şehir ve ilçe.",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}}
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.1)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Dedektif AI Hatası: {e}"); return None

@st.cache_data(ttl=3600)
def run_analyst_ai(_client, headline, summary, facility_name):
    """Aşama 2: Teyit edilmiş kimlik üzerinden derinlemesine hasar analizi yapar."""
    prompt = f"""
    Sen, elit bir sigorta risk analistisin (Analist). Bir hasar olayının yaşandığı tesisin kimliği '{facility_name}' olarak teyit edildi.
    GÖREVİN: Sana verilen orijinal haber metnini kullanarak, bu tesisle ilgili aşağıdaki sigortacılık detaylarını çıkar. Bilmiyorsan "Tespit Edilemedi" yaz.
    - ORİJİNAL HABER: Başlık: "{headline}", Özet: "{summary}"
    - ÇIKTI: Sadece aşağıdaki JSON formatında, başka hiçbir metin olmadan çıktı ver.
    {{
      "hasarin_nedeni_kaynakli": "Hasarın olası nedeni ve bu bilginin kaynağı (örn: 'Elektrik kontağı - İtfaiye raporu').",
      "hasarin_fiziksel_boyutu": "Hasarın fiziksel kapsamı (örn: '5000 m² depo alanı yandı', 'üretim bandı zarar gördü').",
      "etkilenen_degerler": "Hasardan etkilenen spesifik varlıklar (örn: 'hammadde stokları', 'tekstil ürünleri').",
      "is_durmasi_etkisi": "Üretimin veya faaliyetin durup durmadığı hakkında bilgi.",
      "yapilan_mudahale": "Olay yerine kimlerin, nasıl müdahale ettiği.",
      "cevre_etkisi_metinsel": "Haber metninde, komşu tesislere veya çevreye olan etkiden bahsediliyor mu? Varsa detaylandır."
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Analist AI Hatası: {e}"); return None

# ------------------------------------------------------------------------------
# 4. COĞRAFİ ZENGİNLEŞTİRME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=86400)
def get_coords_from_google(api_key, address_text):
    """Google Geocoding API kullanarak adresten kesin koordinat alır."""
    if not api_key or not address_text: return None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address_text)}&key={api_key}&language=tr&region=TR"
        response = requests.get(url)
        results = response.json().get('results', [])
        if results: return results[0].get('geometry', {}).get('location', {})
        return None
    except Exception: return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    """Verilen koordinatlara yakın endüstriyel tesisleri bulur."""
    if not all([api_key, lat, lon]): return []
    try:
        keywords = quote("fabrika|depo|sanayi|tesis|lojistik|antrepo")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius=1000&keyword={keywords}&key={api_key}"
        response = requests.get(url, timeout=10)
        results = response.json().get('results', [])
        return [{
            "tesis_adi": p.get('name'), "adres": p.get('vicinity'), 
            "lat": p.get('geometry',{}).get('location',{}).get('lat'),
            "lng": p.get('geometry',{}).get('location',{}).get('lng')
        } for p in results[:10]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 5. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Son Olaylar")
    events = get_latest_events_from_rss()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        for event in events:
            with st.container(border=True):
                st.markdown(f"**{event['headline']}**")
                st.caption(event['snippet'])
                if st.button("Bu Haberi Seç", key=event['url'], use_container_width=True):
                    st.session_state.selected_event = event
                    st.session_state.stage1_report = None
                    st.session_state.stage2_report = None
                    st.rerun()

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' not in st.session_state:
        st.info("Lütfen sol panelden analiz etmek için bir haber seçin.")
    else:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        
        # --- AŞAMA 1: KİMLİK TESPİTİ ---
        if st.button("1. Adım: Kimliği Tespit Et", type="primary", use_container_width=True):
            if not client: st.error("Lütfen Grok API anahtarını ekleyin.")
            else:
                with st.spinner("Dedektif AI çalışıyor: Tesis kimliği ve konumu araştırılıyor..."):
                    st.session_state.stage1_report = run_detective_ai(client, event['headline'], event['full_summary'])
                    st.session_state.stage2_report = None # 1. adım tekrar çalışınca 2. adımı temizle
        
        # --- AŞAMA 1 SONUÇLARI ---
        if st.session_state.get('stage1_report'):
            s1_report = st.session_state.stage1_report
            st.markdown("---")
            
            col_title, col_score = st.columns([3, 1])
            with col_title:
                st.subheader(f"Tespit Edilen Kimlik: {s1_report.get('tesis_adi', 'Bulunamadı')}")
            with col_score:
                st.metric("Güven Skoru", f"{s1_report.get('guven_skoru', 0)}/5")

            st.info(f"**Kanıt Zinciri:** {s1_report.get('kanit_zinciri', 'N/A')}")

            # --- AŞAMA 2: DETAYLI ANALİZ ---
            is_identified = s1_report.get('tesis_adi') and s1_report.get('tesis_adi') != 'Tespit Edilemedi'
            if is_identified:
                if st.button("2. Adım: Detaylı Hasar Analizi Yap", use_container_width=True):
                    with st.spinner(f"Analist AI çalışıyor: '{s1_report.get('tesis_adi')}' için hasar detayları çıkarılıyor..."):
                        st.session_state.stage2_report = run_analyst_ai(client, event['headline'], event['full_summary'], s1_report.get('tesis_adi'))
            
        # --- AŞAMA 2 SONUÇLARI VE HARİTA ---
        if st.session_state.get('stage2_report'):
            s2_report = st.session_state.stage2_report
            st.markdown("---")
            st.subheader("Derinlemesine Hasar Analizi")

            c1, c2 = st.columns(2)
            c1.warning(f"**Hasarın Nedeni:** {s2_report.get('hasarin_nedeni_kaynakli', 'N/A')}")
            c2.warning(f"**Fiziksel Boyutu:** {s2_report.get('hasarin_fiziksel_boyutu', 'N/A')}")
            c1.info(f"**Etkilenen Değerler:** {s2_report.get('etkilenen_degerler', 'N/A')}")
            c2.info(f"**İş Durması Etkisi:** {s2_report.get('is_durmasi_etkisi', 'N/A')}")
            
            with st.expander("Müdahale ve Çevre Analizi", expanded=False):
                st.success(f"**Yapılan Müdahale:** {s2_report.get('yapilan_mudahale', 'N/A')}")
                st.error(f"**Metinsel Çevre Analizi:** {s2_report.get('cevre_etkisi_metinsel', 'N/A')}")
            
            # --- HARİTA OLUŞTURMA (ÇİFT GÜVENCE SİSTEMİ) ---
            st.subheader("Olay Yeri Haritası ve Çevresel Riskler")
            final_coords = None
            s1_coords = st.session_state.stage1_report.get('tahmini_koordinat')
            if s1_coords and s1_coords.get('lat'):
                final_coords = {'lat': float(s1_coords['lat']), 'lng': float(s1_coords['lon'])}
            else:
                with st.spinner("AI koordinat bulamadı, Google Geocoding ile kesin konum aranıyor..."):
                    address = f"{st.session_state.stage1_report.get('tesis_adi')}, {st.session_state.stage1_report.get('sehir_ilce')}"
                    final_coords = get_coords_from_google(google_api_key, address)

            if final_coords:
                neighbors = find_neighboring_facilities(google_api_key, final_coords['lat'], final_coords['lng'])
                m = folium.Map(location=[final_coords['lat'], final_coords['lng']], zoom_start=14, tiles="CartoDB positron")
                folium.Marker([final_coords['lat'], final_coords['lng']], popup=f"<b>{s1_report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                for n in neighbors:
                    if n.get('lat') and n.get('lng'): folium.Marker([n['lat'], n['lng']], popup=f"<b>{n['tesis_adi']}</b>", tooltip=n['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                folium_static(m, height=400)
                if neighbors: st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])
            else:
                st.warning("Olay konumu harita üzerinde gösterilemedi (Ne AI ne de Google Geocoding koordinat bulamadı).")
