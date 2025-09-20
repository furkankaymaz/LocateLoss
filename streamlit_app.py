# ==============================================================================
#      NİHAİ KOD (v10.1): Caching Hatası Düzeltildi
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import feedparser
from urllib.parse import quote
import requests

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API KEY'LER
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")

# --- API Anahtarları ---
# Grok API
API_SERVICE = "Grok_XAI"
API_CONFIGS = {"Grok_XAI": {"base_url": "https://api.x.ai/v1", "model": "grok-4-fast-reasoning"}}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
grok_api_key = st.secrets.get("GROK_API_KEY")

# Google Maps API
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")

# ------------------------------------------------------------------------------
# 2. AŞAMA 1: OLAY TESPİTİ (GENİŞ AĞ)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=900)
def fetch_potential_events_from_rss():
    search_query = '("fabrika" OR "sanayi" OR "OSB" OR "liman" OR "tersane" OR "depo" OR "antrepo" OR "santral" OR "tesis") AND ("yangın" OR "patlama" OR "kaza" OR "hasar" OR "sızıntı")'
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:30d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": entry.title, "link": entry.link} for entry in feed.entries]
    except Exception as e:
        st.error(f"Haber akışı çekilirken hata: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. AŞAMA 2: AKILLI ÖN ELEME (AI FİLTRE)
# ------------------------------------------------------------------------------
# DÜZELTME: 'client' parametresinin başına '_' eklenerek cache tarafından ignore edilmesi sağlandı.
@st.cache_data(ttl=3600)
def is_event_relevant(_client, headline):
    prompt = f"Bu '{headline}' başlığı, bir endüstriyel/ticari tesiste (fabrika, depo, santral vb.) meydana gelen ve fiziksel hasara (yangın, patlama, çökme vb.) yol açan bir olayı mı anlatıyor? Sadece 'EVET' veya 'HAYIR' olarak cevap ver."
    try:
        response = _client.chat.completions.create(model=SELECTED_CONFIG["model"], messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0.0)
        answer = response.choices[0].message.content.strip().upper()
        return "EVET" in answer
    except Exception:
        return False

# ------------------------------------------------------------------------------
# 4. AŞAMA 3: DERİN ANALİZ (X TEYİDİ VE VERİ ÇIKARMA)
# ------------------------------------------------------------------------------
# DÜZELTME: 'client' parametresinin başına '_' eklenerek cache tarafından ignore edilmesi sağlandı.
@st.cache_data(ttl=3600)
def find_company_name_on_x(_client, headline):
    prompt = f"Sen bir sosyal medya araştırmacısısın. Sana verdiğim şu haber başlığıyla ilgili X (Twitter) üzerinde adı geçen spesifik şirket veya ticari unvanı bul: '{headline}'. Sadece ve sadece bulduğun şirket ismini döndür. Eğer net bir isim bulamazsan 'Belirtilmemiş' yanıtını ver."
    try:
        response = _client.chat.completions.create(model=SELECTED_CONFIG["model"], messages=[{"role": "user", "content": prompt}], max_tokens=50, temperature=0.1)
        return response.choices[0].message.content.strip()
    except Exception:
        return "Belirtilmemiş"

# DÜZELTME: 'client' parametresinin başına '_' eklenerek cache tarafından ignore edilmesi sağlandı.
@st.cache_data(ttl=86400)
def analyze_event_details(_client, headline, url, confirmed_company_name):
    prompt = f"""
    Sen bir sigorta hasar eksperi ve risk analistisin. Sana verilen haberi analiz et.
    Haber Başlığı: "{headline}"
    Haber Linki: {url}
    Teyit Edilmiş Tesis Adı (X'ten bulundu): "{confirmed_company_name}"

    GÖREVİN: Bu bilgileri kullanarak, aşağıdaki anahtarlara sahip detaylı bir JSON raporu oluştur. 'tesis_adi_ticari_unvan' alanında sana verilen teyit edilmiş ismi kullan. Hasar tahminini haber metninden kaynak göstererek yap, ASLA tahmin yürütme.
    JSON ANAHTARLARI: olay_tarihi_saati, guncel_durum, tesis_adi_ticari_unvan, sehir_ilce, olay_tipi_ozet, hasar_tahmini (nesne: tutar_araligi_tl, kaynak, aciklama), can_kaybi_ve_yaralilar (nesne: durum, detaylar), kaynak_linkleri (dizi), gorsel_linkleri (dizi), latitude, longitude
    """
    try:
        response = _client.chat.completions.create(model=SELECTED_CONFIG["model"], messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        st.warning("Detaylı analizden geçerli JSON alınamadı."); st.code(content)
        return None
    except Exception as e:
        st.error(f"Detaylı analiz hatası: {e}")
        return None

# ------------------------------------------------------------------------------
# 5. AŞAMA 4: COĞRAFİ ZENGİNLEŞTİRME (GOOGLE PLACES API)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=250):
    if not api_key:
        st.warning("Google Maps API anahtarı bulunamadı. Komşu tesis analizi atlanıyor.")
        return []
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
    try:
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = []
        for place in results[:5]: 
            neighbors.append({
                "tesis_adi": place.get('name'),
                "tip": ", ".join(place.get('types', [])),
                "konum": place.get('vicinity')
            })
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API'den komşu tesisler alınamadı: {e}")
        return []

# ------------------------------------------------------------------------------
# 6. ARAYÜZ VE KONTROL MEKANİZMASI
# ------------------------------------------------------------------------------
st.sidebar.header("⚙️ Kontrol Paneli")
event_limit = st.sidebar.number_input("Analiz Edilecek Maksimum Olay Sayısı", min_value=1, max_value=10, value=1, help="Maliyeti kontrol etmek için her çalıştırmada kaç olayın derinlemesine analiz edileceğini seçin.")

if st.sidebar.button("En Son Olayları Bul ve Analiz Et", type="primary", use_container_width=True):
    if not grok_api_key:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin.")
        st.stop()

    client = OpenAI(api_key=grok_api_key, base_url=SELECTED_CONFIG["base_url"])
    processed_count = 0
    
    with st.spinner("Aşama 1/5: Potansiyel olaylar haber kaynaklarından taranıyor..."):
        potential_events = fetch_potential_events_from_rss()

    if not potential_events:
        st.warning("Haber kaynaklarında potansiyel bir olay bulunamadı.")
        st.stop()

    st.info(f"{len(potential_events)} potansiyel başlık bulundu. Şimdi akıllı filtre ile eleniyor...")
    
    for event in potential_events:
        if processed_count >= event_limit:
            st.success(f"İstenen olay limitine ({event_limit}) ulaşıldı. Analiz tamamlandı.")
            break

        with st.spinner(f"Aşama 2/5: '{event['title'][:50]}...' filtreleniyor..."):
            if not is_event_relevant(client, event['title']):
                continue

        st.success(f"✅ İlgili olay bulundu: **{event['title']}**")
        
        with st.spinner("Aşama 3/5: Firma adı X (Twitter) üzerinden teyit ediliyor..."):
            company_name = find_company_name_on_x(client, event['title'])
        
        st.write(f"**Teyit Edilen Firma Adı:** {company_name}")

        with st.spinner(f"Aşama 3/5: '{company_name}' için detaylı analiz yapılıyor..."):
            details = analyze_event_details(client, event['title'], event['link'], company_name)
        
        if not details:
            st.warning("Bu olay için detay analizi başarısız oldu. Sonraki olaya geçiliyor.")
            continue
            
        lat = details.get('latitude')
        lon = details.get('longitude')
        real_neighbors = []
        if lat and lon:
            with st.spinner("Aşama 4/5: Gerçek komşu tesisler harita servisinden alınıyor..."):
                real_neighbors = find_neighboring_facilities(google_api_key, lat, lon)
        
        st.subheader(f"📂 Analiz Raporu: {details.get('tesis_adi_ticari_unvan')}")
        
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Özet:** {details.get('olay_tipi_ozet', 'N/A')}")
            hasar = details.get('hasar_tahmini', {})
            st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Belirtilmemiş'), delta=hasar.get('kaynak', ''), delta_color="off")
        
        with col2:
            st.info(f"**Güncel Durum:** {details.get('guncel_durum', 'N/A')}")
            can_kaybi = details.get('can_kaybi_ve_yaralilar', {})
            if can_kaybi.get('durum', 'hayır').lower() == 'evet':
                st.error(f"**Can Kaybı/Yaralı:** {can_kaybi.get('detaylar', 'Detay Yok')}")
        
        if lat and lon:
            m = folium.Map(location=[float(lat), float(lon)], zoom_start=16)
            folium.Marker([float(lat), float(lon)], popup=f"<b>{details.get('tesis_adi_ticari_unvan')}</b>", tooltip="Ana Tesis", icon=folium.Icon(color='red', icon='fire')).add_to(m)
            folium_static(m, height=400)

        with st.expander("Detaylı Raporu ve Kaynakları Görüntüle"):
            st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
            if real_neighbors:
                st.table(pd.DataFrame(real_neighbors))
            else:
                st.write("Yakın çevrede harita servisinden tespit edilen bir tesis bulunamadı.")
            
            st.markdown("##### Kaynak Linkler")
            for link in details.get('kaynak_linkleri', []):
                st.markdown(f"- {link}")

        st.markdown("---")
        processed_count += 1

    if processed_count == 0:
        st.info("Tarama ve filtreleme sonucunda analiz edilecek yeni bir olay bulunamadı.")
