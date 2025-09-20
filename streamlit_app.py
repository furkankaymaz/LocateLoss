# ==============================================================================
#      NİHAİ KOD (v25.0): Veri Çekme (Scraping) + Derin Analiz Mimarisi
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
from bs4 import BeautifulSoup

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

# Adım 1: Otomatik Keşif - En son olayı bulur
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

# YENİ Adım 2: Veri Çekme - Haberin metnini internetten okur
@st.cache_data(ttl=3600)
def scrape_article_text(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status() # HTTP hatalarını kontrol et
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Haber metnini bulmak için genel seçiciler (selector)
        content_selectors = ['div.story-body', 'div.article-content', 'div.content', 'article']
        main_content = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        if not main_content:
            main_content = soup.body # Hiçbir şey bulunamazsa body'yi al
        
        paragraphs = main_content.find_all('p')
        full_text = "\n".join([p.get_text(strip=True) for p in paragraphs])
        return full_text if full_text else "Metin çekilemedi."
    except Exception as e:
        st.warning(f"Haber metni çekilirken hata oluştu: {e}")
        return "Metin çekilemedi."

# Adım 3: Derin Analiz - Çekilmiş veri üzerinden AI'ı çalıştırır
@st.cache_data(ttl=3600)
def get_detailed_report(_client, headline, url, article_text):
    prompt = f"""
    Sen, Türkiye odaklı, kanıta dayalı ve aşırı detaycı bir sigorta istihbarat analistisin.
    
    ANA GÖREVİN: Sana aşağıda tam metnini verdiğim haberi ve başlığını analiz et.
    - BAŞLIK: "{headline}"
    - HABER METNİ: "{article_text[:4000]}"

    İKİNCİL GÖREVİN: Yukarıdaki metinden bulduğun kilit isimler (potansiyel tesis adı, şehir vb.) ile **X (Twitter) üzerinde ek bir arama yaparak** bilgileri doğrula, ek detay, görgü tanığı ve kanıt bul.

    NİHAİ HEDEF: Topladığın TÜM bilgileri (verilen haber metni ve X'ten buldukların) birleştirerek, aşağıdaki JSON formatında, mümkün olan en detaylı ve dolu raporu oluştur.
    
    JSON NESNE YAPISI:
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kanit": Tesis adının geçtiği cümlenin veya X paylaşımının doğrudan alıntısı.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG).
    - "hasarin_nedeni": Olayın tahmini nedeni.
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (yüzölçümü, etkilenen birimler).
    - "maddi_hasar_tahmini": Parasal maddi hasar bilgisi ve kaynağı.
    - "kar_kaybi_tahmini": Üretim durması kaynaklı kar kaybı bilgisi ve kaynağı.
    - "yapilan_mudahale": Resmi kurumların müdahalesi (itfaiye sayısı, süre).
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "cevreye_etki": Duman, sızıntı gibi çevreye olan etkilerin özeti.
    - "latitude", "longitude": Olay yerinin spesifik koordinatları (tahmin de olabilir).
    - "gorsel_url": Olayla ilgili en net fotoğrafın doğrudan URL'si (.jpg, .png).
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi.
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Derin Analiz Motorunda Hata: {e}"); return None

# Adım 4: Coğrafi Zenginleştirme
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = []
        for p in results[:10]:
            loc = p.get('geometry', {}).get('location', {})
            neighbors.append({"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "lat": loc.get('lat'), "lng": loc.get('lng')})
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Tek Olay Analizi")
run_analysis = st.sidebar.button("En Son Önemli Olayı Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En güncel ve önemli tek bir olayı bulur, metnini çeker, derinlemesine analiz eder ve sunar.")

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    report = None
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1: Haber kaynakları taranıyor...")
        event_candidate = get_latest_event_candidate_from_rss()
        
        if not event_candidate:
            status.update(label="Hata! Uygun bir olay adayı bulunamadı.", state="error"); st.stop()
        
        status.write(f"Olay Adayı Bulundu: **{event_candidate['headline']}**")
        status.write(f"Aşama 2: Haber metni '{event_candidate['url']}' adresinden çekiliyor...")
        
        article_text = scrape_article_text(event_candidate['url'])
        
        if "Metin çekilemedi" in article_text:
            status.update(label="Hata! Haber metni çekilemedi.", state="error"); st.stop()
        
        status.write("Aşama 3: AI Analiz Motoru çalıştırılıyor: Çekilen metin ve X üzerinde analiz başlıyor...")
        report = get_detailed_report(client, event_candidate['headline'], event_candidate['url'], article_text)
        
        if report:
            status.write("Aşama 4: Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor...")
            report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
            status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
        else:
            status.update(label="Analiz Başarısız Oldu!", state="error")

    if report:
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
        with col3:
            st.metric(label="Maddi Hasar Tahmini", value=report.get('maddi_hasar_tahmini', 'Tespit Edilemedi'))
        with col4:
            st.metric(label="Kar Kaybı Tahmini", value=report.get('kar_kaybi_tahmini', 'Tespit Edilemedi'))
        
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
                            folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b><br><i>Tip: {neighbor['tip']}</i>", tooltip=neighbor['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=500)
                except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı.")
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak en son olayın analizini başlatın.")
