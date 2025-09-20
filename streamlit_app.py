# ==============================================================================
#      NİHAİ MVP KODU (v29.0): İnteraktif Seçim ve Coğrafi Teyit
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests
import feedparser
from urllib.parse import quote

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

# Adım 1: İnteraktif Seçim İçin Olay Adaylarını Listeler
@st.cache_data(ttl=600)
def get_latest_event_candidates_from_rss():
    search_query = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması" OR "enerji santrali")'
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return []
        # Her aday için başlık ve linki bir sözlük olarak sakla
        candidates = [{"headline": entry.title, "url": entry.link} for entry in feed.entries[:5]]
        return candidates
    except Exception as e:
        st.sidebar.error(f"RSS Hata: {e}"); return []

# Adım 2A: "Araştırmacı" AI - URL içeriğini özetler
@st.cache_data(ttl=3600)
def get_summary_from_url(_client, url):
    prompt = f"Sen bir web araştırma asistanısın. Tek görevin var: Sana verilen '{url}' adresindeki haber makalesinin içeriğini oku ve bana olayın tüm detaylarını içeren, tarafsız ve kapsamlı bir özet metin sun. Sadece haberin kendisine odaklan."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Araştırmacı AI Hatası: {e}"); return None

# Adım 2B: "Analist" AI - Özetlenmiş metinden nihai raporu oluşturur
@st.cache_data(ttl=3600)
def get_detailed_report_from_summary(_client, headline, summary_text):
    prompt = f"""
    Sen elit bir sigorta istihbarat analistisin. Sana bir hasar olayıyla ilgili özetlenmiş bir metin veriyorum.
    - BAŞLIK: "{headline}"
    - OLAY ÖZETİ METNİ: "{summary_text}"

    GÖREVİN: Bu metni ve içindeki anahtar kelimelerle **X (Twitter) üzerinde yapacağın zihinsel araştırmayı** kullanarak, aşağıdaki JSON formatında, mümkün olan en detaylı ve dolu raporu oluştur.
    Özellikle **kar_kaybi_detay** alanı için 'faaliyet durdu mu', 'üretim kaybı var mı' gibi faktörleri metinden çıkarmaya odaklan.
    
    JSON NESNE YAPISI:
    - "tesis_adi", "tesis_adi_kanit", "sehir_ilce", "tahmini_adres_metni", "olay_tarihi",
    - "hasarin_nedeni", "hasarin_fiziksel_boyutu", "yapilan_mudahale",
    - "maddi_hasar_tahmini": Parasal maddi hasar bilgisi ve kaynağı.
    - "kar_kaybi_detay": Üretimin durması, etkilenen hatlar gibi kar kaybına yol açan faktörlerin metinden çıkarılmış özeti.
    - "guncel_durum", "cevreye_etki", "gorsel_url", "kaynak_urller"
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Analist AI Hatası: {e}"); return None

# Adım 3: Konum Teyidi - Google Geocoding API
@st.cache_data(ttl=86400)
def get_coordinates_from_address(api_key, address_text):
    if not api_key or not address_text: return None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address_text)}&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        if results:
            location = results[0].get('geometry', {}).get('location', {})
            return {"lat": location.get('lat'), "lng": location.get('lng')}
        return None
    except Exception as e:
        st.warning(f"Google Geocoding API hatası: {e}"); return None

# Adım 4: Çevre Analizi - Google Places API
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "lat": p.get('geometry', {}).get('location', {}).get('lat'), "lng": p.get('geometry', {}).get('location', {}).get('lng')} for p in results[:10]]
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Olay Seçimi ve Analiz")
event_candidates = get_latest_event_candidates_from_rss()

if not event_candidates:
    st.sidebar.error("Son olay adayları çekilemedi. Lütfen daha sonra tekrar deneyin.")
else:
    # Adayları sadece başlık olarak göster
    headlines = [f"{i+1}. {c['headline']}" for i, c in enumerate(event_candidates)]
    selected_headline = st.sidebar.radio("Analiz için bir olay seçin:", headlines, index=0)
    
    run_analysis = st.sidebar.button("Seçilen Olayı Analiz Et", type="primary", use_container_width=True)
    st.sidebar.caption("Seçilen olayı AI ile analiz eder ve Google Maps ile zenginleştirir.")

    if run_analysis:
        if not client:
            st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()
        if not google_api_key:
            st.error("Lütfen Google Maps API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

        # Seçilen başlığa karşılık gelen tam aday nesnesini bul
        selected_index = headlines.index(selected_headline)
        selected_event = event_candidates[selected_index]
        report = None
        
        with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
            status.write(f"Aşama 1: '{selected_event['headline']}' haberinin içeriği özetleniyor...")
            summary_text = get_summary_from_url(client, selected_event['url'])
            
            if not summary_text:
                status.update(label="Hata! Haber metni özetlenemedi.", state="error"); st.stop()

            status.write("Aşama 2: Özetlenmiş metinden detaylı rapor oluşturuluyor...")
            report = get_detailed_report_from_summary(client, selected_event['headline'], summary_text)
            
            if report:
                report['kaynak_urller'] = [selected_event['url']]
                
                status.write("Aşama 3: Adres verisiyle konum teyit ediliyor (Google Geocoding)...")
                address_text = report.get('tahmini_adres_metni', report.get('sehir_ilce'))
                coordinates = get_coordinates_from_address(google_api_key, address_text)
                
                if coordinates:
                    report['latitude'] = coordinates['lat']
                    report['longitude'] = coordinates['lng']
                    status.write("Aşama 4: Komşu tesisler aranıyor (Google Places)...")
                    report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, coordinates['lat'], coordinates['lng'])
                else:
                    st.warning("Olay için hassas konum bulunamadı, komşu tesis analizi atlanıyor.")
                    report['komsu_tesisler_harita'] = []
                
                status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
            else:
                status.update(label="Detaylı Rapor Oluşturulamadı!", state="error")

        if report:
            st.markdown("---")
            st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
            
            if report.get('gorsel_url'):
                st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (AI Tarafından Bulundu)")

            st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"*")
            
            st.subheader("Hasar Analizi")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("##### Maddi Hasar")
                st.warning(f"**Fiziksel Boyut:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
                st.metric(label="Maddi Hasar Tahmini", value=report.get('maddi_hasar_tahmini', 'Tespit Edilemedi'))
            with col2:
                st.markdown("##### İş Durması / Kar Kaybı")
                st.warning(f"**Etki:** {report.get('kar_kaybi_detay', 'N/A')}")
            
            st.subheader("Olay Yönetimi ve Etkileri")
            col3, col4, col5 = st.columns(3)
            with col3: st.info(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            with col4: st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            with col5: st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
            st.info(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Tespit Edilemedi.')}")

            with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
                lat, lon = report.get('latitude'), report.get('longitude')
                if lat and lon:
                    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
                    folium.Marker([lat, lon], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    neighbors = report.get('komsu_tesisler_harita', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b>", tooltip=neighbor['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=500)
                else:
                    st.info("Rapor, harita çizimi için hassas koordinat bilgisi içermiyor.")

                st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
                st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
