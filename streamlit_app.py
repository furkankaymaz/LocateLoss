# ==============================================================================
#      NİHAİ KOD (v31.0): Aşamalı Teyit Protokolü
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
# 2. PROTOKOL FONKSİYONLARI (ADIM ADIM)
# ------------------------------------------------------------------------------

# Adım 1A: Olay Adaylarını RSS'ten Çekme
@st.cache_data(ttl=600)
def get_event_candidates_from_rss():
    search_query = '("fabrika" OR "sanayi" OR "OSB") AND ("yangın" OR "patlama" OR "kaza")'
    rss_url = f"https://news.google.com/rss/search?q={quote(search_query)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"headline": entry.title, "url": entry.link} for entry in feed.entries[:20]]
    except Exception as e:
        st.sidebar.error(f"RSS Hata: {e}"); return []

# Adım 1B: "Kapıdaki Bekçi" AI Filtresi
@st.cache_data(ttl=3600)
def filter_relevant_headlines(_client, candidates):
    relevant_headlines = []
    for candidate in candidates:
        prompt = f"'{candidate['headline']}' başlıklı haber, bir endüstriyel tesisteki spesifik bir fiziksel hasar (yangın, patlama vb.) hakkında mı? İdari bir duyuru (ÇED raporu gibi) değil, gerçek bir kaza haberi mi? Sadece 'Evet' veya 'Hayır' de."
        try:
            response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=5, temperature=0.0)
            if "evet" in response.choices[0].message.content.strip().lower():
                relevant_headlines.append(candidate)
        except Exception: continue
    return relevant_headlines

# Adım 2: "Araştırmacı" AI - URL içeriğini özetler
@st.cache_data(ttl=3600)
def get_summary_from_url(_client, url):
    prompt = f"Sen bir web araştırma asistanısın. Görevin, sana verilen '{url}' adresindeki haber makalesinin içeriğini oku ve bana olayın tüm detaylarını içeren, tarafsız ve kapsamlı bir özet metin sun. Sadece haberin kendisine odaklan."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Araştırmacı AI Hatası: {e}"); return None

# Adım 3: Varlık Çıkarımı - X'te arama için anahtar kelime üretir
@st.cache_data(ttl=3600)
def extract_search_entities(_client, summary_text):
    prompt = f"Sana verilen haber metnini oku. X'te arama yapmak için kullanılabilecek en spesifik anahtar kelimeleri çıkar. Sadece şu formatta bir JSON ver: {{\"en_spesifik_konum\": \"...\", \"potansiyel_isimler\": [\"...\", \"...\"], \"olay_tipi\": \"...\"}}."
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=512, temperature=0.0)
        content = response.choices[0].message.content; match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception: return {}

# Adım 4: "Kontrollü Dedektif" AI - X'ten Tesis Adı Teyidi
@st.cache_data(ttl=3600)
def find_company_name_on_x_controlled(_client, entities):
    prompt = f"""Sen bir OSINT uzmanısın. Görevin, SADECE sana verdiğim spesifik anahtar kelimelerle X (Twitter) üzerinde arama yaparak olayın yaşandığı **tesisin ticari unvanını** bulmaktır.
    ARAMA ÇERÇEVEN: Konum: '{entities.get('en_spesifik_konum', '')}', Olay: '{entities.get('olay_tipi', '')}', Potansiyel İsimler: {entities.get('potansiyel_isimler', [])}.
    Bu çerçevenin dışına çıkma. Bulduğun ismi ve **kanıtını (doğrudan alıntı veya tweet linki)** bana ver. Yüksek kesinlikle bir isim bulamazsan 'Tespit Edilemedi' de. ASLA İSİM UYDURMA.
    ÇIKTI FORMATI: {{"tesis_adi": "...", "kanit": "..."}}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=1024, temperature=0.0)
        content = response.choices[0].message.content; match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else {"tesis_adi": "Tespit Edilemedi", "kanit": "AI yanıt formatı bozuk."}
    except Exception: return None

# Adım 5: "Analist" AI - Nihai Rapor
@st.cache_data(ttl=3600)
def get_final_report(_client, summary_text, verified_name, proof):
    prompt = f"""Sen elit bir sigorta analistisin. Olayın **{verified_name}** firmasında yaşandığı teyit edildi (Kanıt: *"{proof}"*).
    GÖREVİN: Sana verilen aşağıdaki **olay özeti metnini** kullanarak, teyit edilmiş bu tesisle ilgili tüm detayları içeren nihai JSON raporunu oluştur.
    OLAY ÖZETİ METNİ: "{summary_text}"
    JSON NESNE YAPISI: "sehir_ilce", "tahmini_adres_metni", "olay_tarihi", "hasarin_nedeni", "hasarin_fiziksel_boyutu", "yapilan_mudahale", "maddi_hasar_detay", "kar_kaybi_detay", "guncel_durum", "cevreye_etki", "gorsel_url"
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content; match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception: return None

# Adım 6 & 7: Google API'ları ile Zenginleştirme
@st.cache_data(ttl=86400)
def get_coordinates_from_address(api_key, address_text):
    if not api_key or not address_text: return None
    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address_text)}&key={api_key}&language=tr&region=TR"
        response = requests.get(url); results = response.json().get('results', [])
        if results: return results[0].get('geometry', {}).get('location', {})
        return None
    except Exception: return None
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis&key={api_key}"
        response = requests.get(url); results = response.json().get('results', [])
        neighbors = [{"tesis_adi": p.get('name'),"tip": ", ".join(p.get('types', [])), "lat": p.get('geometry',{}).get('location',{}).get('lat'),"lng": p.get('geometry',{}).get('location',{}).get('lng')} for p in results[:10]]
        return neighbors
    except Exception: return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Olay Seçimi ve Analiz")

# Adım 1: Olay Adaylarını listele
with st.spinner("İlgili olay adayları taranıyor..."):
    all_candidates = get_event_candidates_from_rss()
    if all_candidates:
        event_candidates = filter_relevant_headlines(client, all_candidates)
    else:
        event_candidates = []

if not event_candidates:
    st.sidebar.error("Analiz edilecek uygun bir olay adayı bulunamadı.")
else:
    headlines = [f"{i+1}. {c['headline']}" for i, c in enumerate(event_candidates)]
    selected_headline = st.sidebar.radio("Analiz için bir olay seçin:", headlines, index=0)
    run_analysis = st.sidebar.button("Seçilen Olayı Analiz Et", type="primary", use_container_width=True)

    if run_analysis:
        if not all([client, google_api_key]):
            st.error("Lütfen Grok ve Google API anahtarlarını eklediğinizden emin olun."); st.stop()

        selected_index = headlines.index(selected_headline)
        selected_event = event_candidates[selected_index]
        report = None
        
        with st.status("Akıllı Teyit Protokolü yürütülüyor...", expanded=True) as status:
            # Adım 2: Özetleme
            status.write(f"Adım 1/5: '{selected_event['headline']}' haberinin içeriği özetleniyor...")
            summary_text = get_summary_from_url(client, selected_event['url'])
            if not summary_text: status.update(label="Hata! Haber metni özetlenemedi.", state="error"); st.stop()

            # Adım 3: Varlık Çıkarımı
            status.write("Adım 2/5: X'te arama için anahtar kelimeler metinden çıkarılıyor...")
            entities = extract_search_entities(client, summary_text)
            if not entities: status.update(label="Hata! Metinden anahtar kelime çıkarılamadı.", state="error"); st.stop()
            
            # Adım 4: Kontrollü X Taraması
            status.write(f"Adım 3/5: '{entities.get('en_spesifik_konum')}' konumu için X'te tesis adı aranıyor...")
            name_proof = find_company_name_on_x_controlled(client, entities)
            if not name_proof or name_proof.get('tesis_adi') == 'Tespit Edilemedi':
                status.update(label="Tesis Adı Teyit Edilemedi!", state="error"); st.error(f"Bu olay için spesifik bir tesis adı X üzerinden teyit edilemedi. Kanıt: {name_proof.get('kanit', 'N/A')}"); st.stop()
            
            verified_name = name_proof['tesis_adi']
            proof = name_proof['kanit']
            status.write(f"Adım 4/5: Tesis adı '{verified_name}' olarak teyit edildi! Nihai rapor oluşturuluyor...")

            # Adım 5: Nihai Raporlama
            report = get_final_report(client, summary_text, verified_name, proof)
            
            if report:
                report['tesis_adi'] = verified_name; report['tesis_adi_kanit'] = proof; report['kaynak_url'] = selected_event['url']
                
                status.write("Adım 5/5: Rapor coğrafi verilerle zenginleştiriliyor...")
                address_text = report.get('tahmini_adres_metni', report.get('sehir_ilce'))
                coordinates = get_coordinates_from_address(google_api_key, address_text)
                if coordinates:
                    report['latitude'] = coordinates['lat']; report['longitude'] = coordinates['lng']
                    report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, coordinates['lat'], coordinates['lng'])
                
                status.update(label="Protokol Başarıyla Tamamlandı!", state="complete", expanded=False)
                st.session_state.report = report # Raporu session state'e kaydet
            else:
                status.update(label="Nihai Rapor Oluşturulamadı!", state="error")
                st.session_state.report = None

if 'report' in st.session_state and st.session_state.report:
    report = st.session_state.report
    # Raporu gösterme kodu...
    st.markdown("---"); st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
    if report.get('gorsel_url'): st.image(report['gorsel_url'])
    st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"*")
    st.subheader("Hasar Detayları")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Maddi Hasar"); st.warning(f"**Fiziksel Boyut:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}"); st.info(f"**Detaylar:** {report.get('maddi_hasar_detay', 'N/A')}")
    with col2:
        st.markdown("##### İş Durması / Kar Kaybı"); st.warning(f"**Etki:** {report.get('kar_kaybi_detay', 'N/A')}")
    st.subheader("Olay Yönetimi ve Etkileri")
    col3, col4 = st.columns(2)
    with col3: st.info(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}"); st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
    with col4: st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}"); st.info(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Tespit Edilemedi.')}")
    with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
        lat, lon = report.get('latitude'), report.get('longitude')
        if lat and lon:
            m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
            folium.Marker([lat, lon], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
            neighbors = report.get('komsu_tesisler_harita', [])
            if neighbors:
                for n in neighbors:
                    if n.get('lat') and n.get('lng'): folium.Marker([n['lat'], n['lng']], popup=f"<b>{n['tesis_adi']}</b>", tooltip=n['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
            folium_static(m, height=500)
        else:
            st.info("Rapor, harita çizimi için hassas koordinat bilgisi içermiyor.")
        st.markdown("##### Komşu Tesisler (Google Harita Verisi)"); st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
