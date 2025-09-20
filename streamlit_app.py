# ==============================================================================
#      NİHAİ KOD (v11.0): Hibrit Arama ve Akıllı Filtreleme Mimarisi
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
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. AŞAMA 1: DİNAMİK OLAY TESPİTİ (KULLANICI FİLTRELERİNE GÖRE)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=900)
def fetch_potential_events_from_rss(tesis_tipleri=None, hasar_tipleri=None, konum=None):
    base_query = []
    
    # Kullanıcı Tesis Tipi filtresi girdiyse, ilgili anahtar kelimeleri oluştur
    if tesis_tipleri:
        tesis_q = [f'"{t}"' for t in tesis_tipleri]
        base_query.append(f"({' OR '.join(tesis_q)})")
    else: # Varsayılan geniş arama
        base_query.append('("fabrika" OR "sanayi" OR "OSB" OR "liman" OR "tersane" OR "depo" OR "santral" OR "tesis")')

    # Kullanıcı Hasar Tipi filtresi girdiyse
    if hasar_tipleri:
        hasar_q = [f'"{h}"' for h in hasar_tipleri]
        base_query.append(f"({' OR '.join(hasar_q)})")
    else: # Varsayılan geniş arama
        base_query.append('("yangın" OR "patlama" OR "kaza" OR "hasar" OR "sızıntı")')
        
    # Kullanıcı Konum filtresi girdiyse
    if konum:
        base_query.append(f'"{konum}"')

    search_query = " AND ".join(base_query)
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:45d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        st.session_state['last_rss_url'] = rss_url # Debug için URL'i kaydet
        return [{"title": entry.title, "link": entry.link} for entry in feed.entries]
    except Exception as e:
        st.error(f"Haber akışı çekilirken hata: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. AŞAMA 2: AKILLI SKORLAMA FİLTRESİ
# ------------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def get_relevance_score(_client, headline):
    prompt = f"""Bir sigorta eksperinin gözünden, bu '{headline}' başlığının endüstriyel bir tesisteki fiziksel hasar olayıyla ilgililik düzeyini 0 (ilgisiz - örn: ekonomi haberi) ile 10 (çok ilgili - örn: fabrika yangını) arasında puanla. Cevabını {{'skor': <puan>, 'sebep': '<1 cümlelik gerekçe>'}} formatında bir JSON olarak ver."""
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=100, temperature=0.0)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return {'skor': 0, 'sebep': 'Geçersiz format'}
    except Exception:
        return {'skor': 0, 'sebep': 'API Hatası'}

# ... Diğer analiz fonksiyonları (find_company_name_on_x, analyze_event_details, find_neighboring_facilities) bir önceki versiyondan (v10.1) kopyalanabilir, onlarda değişiklik yok.
# Okunabilirlik için buraya tekrar ekliyorum:

@st.cache_data(ttl=3600)
def find_company_name_on_x(_client, headline):
    prompt = f"Sen bir sosyal medya araştırmacısısın. Sana verdiğim şu haber başlığıyla ilgili X (Twitter) üzerinde adı geçen spesifik şirket veya ticari unvanı bul: '{headline}'. Sadece ve sadece bulduğun şirket ismini döndür. Eğer net bir isim bulamazsan 'Belirtilmemiş' yanıtını ver."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=50, temperature=0.1)
        return response.choices[0].message.content.strip()
    except Exception: return "Belirtilmemiş"

@st.cache_data(ttl=86400)
def analyze_event_details(_client, headline, url, confirmed_company_name):
    prompt = f"""Sen bir sigorta hasar eksperi ve risk analistisin. Sana verilen haberi analiz et. Haber Başlığı: "{headline}", Haber Linki: {url}, Teyit Edilmiş Tesis Adı: "{confirmed_company_name}". GÖREVİN: Bu bilgileri kullanarak, detaylı bir JSON raporu oluştur. 'tesis_adi_ticari_unvan' alanında sana verilen teyit edilmiş ismi kullan. Hasar tahminini haber metninden kaynak göstererek yap, ASLA tahmin yürütme. JSON ANAHTARLARI: olay_tarihi_saati, guncel_durum, tesis_adi_ticari_unvan, sehir_ilce, olay_tipi_ozet, hasar_tahmini (nesne: tutar_araligi_tl, kaynak, aciklama), can_kaybi_ve_yaralilar (nesne: durum, detaylar), kaynak_linkleri (dizi), gorsel_linkleri (dizi), latitude, longitude"""
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match: return json.loads(match.group(0))
        return None
    except Exception: return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=250):
    if not api_key: return []
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
    try:
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:5]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE KONTROL MEKANİZMASI
# ------------------------------------------------------------------------------
st.sidebar.header("Manuel Arama Filtreleri")
tesis_opsiyon = st.sidebar.multiselect("Tesis Tipi", ["fabrika", "depo", "enerji santrali", "liman", "tersane", "sanayi sitesi", "OSB"])
hasar_opsiyon = st.sidebar.multiselect("Hasar Tipi", ["yangın", "patlama", "kimyasal sızıntı", "çökme", "kaza"])
konum_opsiyon = st.sidebar.text_input("Konum (İl / İlçe / OSB Adı)")

run_manual_search = st.sidebar.button("Filtrele ve Ara", type="primary")
st.sidebar.divider()
st.sidebar.header("Otomatik Tarama")
run_auto_search = st.sidebar.button("Son Olayları Otomatik Bul")

# --- ANA İŞLEM BLOKU ---
def process_events(event_list):
    if not event_list:
        st.warning("Belirtilen kriterlere uygun haber bulunamadı.")
        if 'last_rss_url' in st.session_state:
            st.caption(f"Denenen Arama Linki: {st.session_state['last_rss_url']}")
        return

    st.info(f"{len(event_list)} potansiyel başlık bulundu. Şimdi Akıllı Filtre ile eleniyor...")
    
    relevant_events = []
    placeholder = st.empty()
    for i, event in enumerate(event_list):
        placeholder.text(f"Filtreleniyor: {i+1}/{len(event_list)} - {event['title'][:50]}...")
        score_data = get_relevance_score(client, event['title'])
        if score_data['skor'] > 6: # Eşik değeri 6 olarak belirlendi
            relevant_events.append(event)
    placeholder.empty()

    if not relevant_events:
        st.warning("Tarama sonucunda, Akıllı Filtre'den geçen anlamlı bir olay bulunamadı.")
        return
        
    st.success(f"Akıllı Filtre'den geçen {len(relevant_events)} adet anlamlı olay bulundu. Şimdi detaylı analiz başlıyor...")

    for event in relevant_events:
        st.markdown("---")
        st.subheader(f" olay Analizi: {event['title']}")
        
        # Derin Analiz Aşamaları
        with st.spinner("Firma adı X üzerinden teyit ediliyor..."):
            company_name = find_company_name_on_x(client, event['title'])
        st.caption(f"Tespit Edilen Firma Adı: {company_name}")

        with st.spinner("Detaylı hasar raporu oluşturuluyor..."):
            details = analyze_event_details(client, event['title'], event['link'], company_name)
        if not details: 
            st.error("Bu olay için detaylı rapor oluşturulamadı.")
            continue

        # Coğrafi Zenginleştirme
        lat, lon = details.get('latitude'), details.get('longitude')
        real_neighbors = find_neighboring_facilities(google_api_key, lat, lon) if lat and lon else []

        # Raporu Ekrana Bas
        # ... (v10.1'deki raporlama ve harita kodu buraya gelecek)
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Özet:** {details.get('olay_tipi_ozet', 'N/A')}")
            hasar = details.get('hasar_tahmini', {})
            st.metric(label="Hasar Tahmini", value=hasar.get('tutar_araligi_tl', 'Belirtilmemiş'), delta=hasar.get('kaynak', ''), delta_color="off")
        with col2:
            st.info(f"**Güncel Durum:** {details.get('guncel_durum', 'N/A')}")
            can_kaybi = details.get('can_kaybi_ve_yaralilar', {})
            if can_kaybi and can_kaybi.get('durum', 'hayır').lower() == 'evet':
                st.error(f"**Can Kaybı/Yaralı:** {can_kaybi.get('detaylar', 'Detay Yok')}")
        
        if lat and lon:
            try:
                m = folium.Map(location=[float(lat), float(lon)], zoom_start=16)
                folium.Marker([float(lat), float(lon)], popup=f"<b>{details.get('tesis_adi_ticari_unvan')}</b>", tooltip="Ana Tesis", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                folium_static(m, height=400)
            except (ValueError, TypeError):
                st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
        
        with st.expander("Detaylı Raporu, Komşu Tesisleri ve Kaynakları Görüntüle"):
            st.markdown("##### Gerçek Komşu Tesisler (Google Maps Verisi)")
            st.table(pd.DataFrame(real_neighbors)) if real_neighbors else st.write("Yakın çevrede harita servisinden tesis tespit edilemedi.")
            st.markdown("##### Kaynak Linkler")
            for link in details.get('kaynak_linkleri', []): st.markdown(f"- {link}")


# Butonlara basılma durumunu kontrol et
if run_manual_search or run_auto_search:
    if not grok_api_key or not google_api_key:
        st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin.")
    else:
        # Hangi butona basıldıysa ona göre parametreleri ayarla
        if run_manual_search:
            events = fetch_potential_events_from_rss(tesis_tipleri=tesis_opsiyon, hasar_tipleri=hasar_opsiyon, konum=konum_opsiyon)
        else: # run_auto_search
            events = fetch_potential_events_from_rss()
        
        process_events(events)
