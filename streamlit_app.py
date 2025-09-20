# ==============================================================================
#      NİHAİ MVP KODU (v28.0): İki Aşamalı AI Analizi (Araştırmacı -> Analist)
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
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analizi")
st.title("🛰️ Akıllı Endüstriyel Hasar Analiz Motoru")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

# Adım 1: En son olayın URL'ini bulur
@st.cache_data(ttl=600)
def get_latest_event_candidate_from_rss():
    search_query = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması" OR "enerji santrali")'
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        latest_entry = feed.entries[0]
        return {"headline": latest_entry.title, "url": latest_entry.link}
    except Exception as e:
        st.error(f"RSS haber kaynağına erişilirken hata oluştu: {e}"); return None

# YENİ Adım 2: "Araştırmacı" AI - Verilen URL'in içeriğini özetler
@st.cache_data(ttl=3600)
def get_summary_from_url(_client, url):
    prompt = f"""
    Sen bir web araştırma asistanısın. Tek görevin var: Sana verilen '{url}' adresindeki haber makalesinin içeriğini oku ve bana olayın tüm detaylarını içeren, tarafsız ve kapsamlı bir özet metin sun. Reklamları ve alakasız kısımları atla, sadece haberin kendisine odaklan.
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Araştırmacı AI (Özet Çıkarma) Hatası: {e}"); return None

# Adım 3: "Analist" AI - Özetlenmiş metinden nihai raporu oluşturur
@st.cache_data(ttl=3600)
def get_detailed_report_from_summary(_client, headline, summary_text):
    prompt = f"""
    Sen elit bir sigorta istihbarat analistisin. Sana bir hasar olayıyla ilgili, başka bir AI tarafından özetlenmiş olan aşağıdaki metni ve olayın başlığını veriyorum.
    - BAŞLIK: "{headline}"
    - OLAY ÖZETİ METNİ: "{summary_text}"

    GÖREVİN: Bu metni ve içindeki anahtar kelimelerle **X (Twitter) üzerinde yapacağın zihinsel araştırmayı** kullanarak, aşağıdaki JSON formatında, mümkün olan en detaylı ve dolu raporu oluştur.
    
    JSON NESNE YAPISI:
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kanit": Tesis adının geçtiği cümlenin veya X paylaşımının doğrudan alıntısı.
    - "sehir_ilce", "olay_tarihi", "hasarin_nedeni", "hasarin_fiziksel_boyutu", "yapilan_mudahale",
    - "maddi_hasar_tahmini": Parasal maddi hasar bilgisi ve kaynağı.
    - "kar_kaybi_tahmini": Üretim durması kaynaklı kar kaybı bilgisi ve kaynağı.
    - "guncel_durum", "cevreye_etki", "latitude", "longitude",
    - "gorsel_url": Olayla ilgili en net fotoğrafın doğrudan URL'si (.jpg, .png).
    - "kaynak_urller": Orijinal haberin linki.
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Analist AI (Rapor Oluşturma) Hatası: {e}"); return None

# Adım 4: Coğrafi Zenginleştirme
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "lat": p.get('geometry', {}).get('location', {}).get('lat'), "lng": p.get('geometry', {}).get('location', {}).get('lng')} for p in results[:10]]
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Tek Olay Analizi")
run_analysis = st.sidebar.button("En Son Önemli Olayı Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En güncel olayı bulur, içeriğini özetler ve detaylı analiz eder.")

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    report = None
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1/4: Haber kaynakları taranıyor...")
        event_candidate = get_latest_event_candidate_from_rss()
        if not event_candidate:
            status.update(label="Hata! Uygun bir olay adayı bulunamadı.", state="error"); st.stop()
        
        status.write(f"Olay Adayı Bulundu: **{event_candidate['headline']}**")
        status.write(f"Aşama 2/4: 'Araştırmacı AI' çalışıyor: '{event_candidate['url']}' adresindeki haberin içeriği özetleniyor...")
        
        summary_text = get_summary_from_url(client, event_candidate['url'])
        if not summary_text:
            status.update(label="Hata! Haber metni AI tarafından özetlenemedi.", state="error"); st.stop()

        status.write("Aşama 3/4: 'Analist AI' çalışıyor: Özetlenmiş metinden detaylı rapor oluşturuluyor...")
        report = get_detailed_report_from_summary(client, event_candidate['headline'], summary_text)
        
        if report:
            report['kaynak_urller'] = [event_candidate['url']] # Orijinal linki ekle
            status.write("Aşama 4/4: Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor...")
            report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
            status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
        else:
            status.update(label="Analiz Başarısız Oldu!", state="error")

    if report:
        # Raporu gösterme kodu (v24 ile büyük ölçüde aynı)
        st.markdown("---")
        st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        if report.get('gorsel_url'):
            st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (AI Tarafından Bulundu)")
        st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"*")
        col1, col2 = st.columns(2)
        with col1:
            st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
        with col2:
            st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
        col3, col4 = st.columns(2)
        with col3: st.metric(label="Maddi Hasar Tahmini", value=report.get('maddi_hasar_tahmini', 'Tespit Edilemedi'))
        with col4: st.metric(label="Kar Kaybı Tahmini", value=report.get('kar_kaybi_tahmini', 'Tespit Edilemedi'))
        st.info(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Tespit Edilemedi.')}")

        with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
            lat, lon = report.get('latitude'), report.get('longitude')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    neighbors = report.get('komsu_tesisler_harita', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b>", tooltip=neighbor['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=500)
                except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı.")
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak analiz sürecini başlatın.")
