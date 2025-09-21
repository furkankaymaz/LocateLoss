# ==============================================================================
#  NİHAİ KOD (v43.0): Derinlemesine Analiz ve Gelişmiş Filtreleme
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
st.set_page_config(layout="wide", page_title="Derinlemesine Hasar Analizi")
st.title("🛰️ Derinlemesine Hasar İstihbarat Motoru")

grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_latest_events_from_rss_deduplicated():
    """Google News RSS'ten en son olayları çeker, tarihe göre sıralar ve tekilleştirir."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []
        
        # GÜNCELLEME: Haberleri en yeniden en eskiye doğru sırala
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
                "summary": summary_text,
                "url": entry.link
            })
            seen_headlines.append(headline)

        return unique_articles[:15]
    except Exception as e:
        st.error(f"RSS akışı okunurken hata: {e}")
        return []

@st.cache_data(ttl=3600)
def analyze_event_with_deep_dive(_client, headline, summary):
    """
    Verilen olayı, sigortacılık perspektifiyle derinlemesine analiz eder, 
    Google arama simülasyonu yapar ve kanıt zinciri oluşturur.
    """
    # GÜNCELLEME: Prompt, sigortacılık detayları ve metinsel çevre analizi için tamamen yeniden yazıldı.
    prompt = f"""
    Sen, internetin tamamını taramış, detay odaklı, elit bir sigorta ve risk istihbarat analistisin.
    Görevin, sana verilen ipuçlarını kullanarak bir Google Arama simülasyonu yapmak ve olayı en ince detayına kadar analiz etmektir. Halüsinasyona sıfır toleransın var. Bilmiyorsan "Tespit Edilemedi" yaz.

    SANA VERİLEN İPUÇLARI:
    - BAŞLIK: "{headline}"
    - ÖZET: "{summary}"

    ANALİZ ADIMLARI VE JSON ÇIKTI YAPISI (SADECE JSON VER, AÇIKLAMA EKLEME):
    1.  **Kimlik Tespiti:** Arama simülasyonu ile tesisin ticari unvanını bul. Birden fazla güvenilir kaynağı (resmi kurum, AA/DHA, yerel basın) çapraz kontrol et.
    2.  **Hasar Analizi:** Olayın sigortacılık açısından kritik detaylarını çıkar.
    3.  **Operasyonel Etki:** İş durması ve müdahale süreçlerini analiz et.
    4.  **Çevre Analizi:** Hem haber metninden hem de tahmini koordinatlardan yola çıkarak çevresel riskleri değerlendir.

    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan.",
      "guven_skoru": "1-5 arası bir sayı. (5 = Çoklu resmi kaynak teyidi)",
      "kanit_zinciri": "Bu isme nasıl ulaştığının, hangi kaynakların (örn: DHA, Belediye X hesabı) teyit ettiğinin ve güven skorunun nedeninin detaylı açıklaması.",
      "sehir_ilce": "Olayın yaşandığı net konum.",
      
      "hasarin_nedeni_kaynakli": "Hasarın olası nedeni ve bu bilginin kaynağı (örn: 'İlk belirlemelere göre elektrik kontağı - İtfaiye raporu').",
      "hasarin_fiziksel_boyutu": "Hasarın fiziksel kapsamı (örn: '5000 metrekarelik depo alanı tamamen yandı', 'üretim bandındaki 3 makine zarar gördü').",
      "etkilenen_degerler": "Haberde geçen, hasardan etkilenen spesifik varlıklar (örn: 'hammadde stokları', 'tekstil ürünleri', 'plastik paletler').",

      "is_durmasi_etkisi": "Üretimin veya faaliyetin durup durmadığı, ne kadar süreceği hakkında bilgi (örn: 'Tesisin faaliyeti geçici olarak durduruldu').",
      "yapilan_mudahale": "Olay yerine kimlerin, ne tür ekipmanlarla müdahale ettiği (örn: '15 itfaiye aracı ve 30 personel sevk edildi').",
      "guncel_durum": "Söndürme, soğutma, hasar tespiti gibi en son operasyonel durum.",
      
      "cevre_etkisi_metinsel": "Haber metninde, alevlerin/dumanın/sızıntının komşu tesislere veya çevreye olan etkisinden bahsediliyor mu? Varsa detaylandır.",
      
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}}
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        st.error(f"AI, geçerli bir JSON formatı üretemedi. Ham yanıt: {content}")
        return None
    except Exception as e:
        st.error(f"AI Analizi sırasında hata oluştu: {e}")
        return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        keywords = quote("fabrika|depo|sanayi|tesis|lojistik|antrepo")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius=1000&keyword={keywords}&key={api_key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        results = response.json().get('results', [])
        
        neighbors = [{
            "tesis_adi": p.get('name'), 
            "adres": p.get('vicinity'), 
            "lat": p.get('geometry',{}).get('location',{}).get('lat'),
            "lng": p.get('geometry',{}).get('location',{}).get('lng')
        } for p in results[:10]]
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API ile komşu tesisler çekilirken hata oluştu: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Son Olaylar")
    with st.spinner("Güncel ve tekil haberler taranıyor..."):
        events = get_latest_events_from_rss_deduplicated()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        event_map = {f"{event['headline']}": event for event in events}
        selected_headline = st.radio("Analiz için bir olay seçin:", event_map.keys(), label_visibility="collapsed")
        st.session_state.selected_event = event_map[selected_headline]

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' in st.session_state:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        st.caption(f"Kaynak: [{event['url']}]({event['url']})")
        
        if st.button("🤖 Bu Olayı Derinlemesine Analiz Et", type="primary", use_container_width=True):
            if not client or not google_api_key:
                st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin.")
            else:
                with st.spinner("AI, arama simülasyonu ile derinlemesine istihbarat topluyor..."):
                    report = analyze_event_with_deep_dive(client, event['headline'], event['summary'])
                    if report:
                        coords = report.get('tahmini_koordinat', {})
                        lat, lon = coords.get('lat'), coords.get('lon')
                        if lat and lon:
                            report['komsu_tesisler'] = find_neighboring_facilities(google_api_key, lat, lon)
                    st.session_state.report = report
        
        if 'report' in st.session_state and st.session_state.report:
            report = st.session_state.report
            st.markdown("---")
            
            col_title, col_score = st.columns([4, 1])
            with col_title:
                st.subheader(f"Rapor: {report.get('tesis_adi', 'Teyit Edilemedi')}")
            with col_score:
                score = report.get('guven_skoru', 0)
                st.metric(label="Güven Skoru", value=f"{score}/5", help="AI'ın bu tespiti yaparkenki güven seviyesi (1=Zayıf, 5=Çok Güçlü)")

            st.info(f"**Kanıt Zinciri:** {report.get('kanit_zinciri', 'N/A')}")
            
            # GÜNCELLEME: Rapor gösterimi daha detaylı ve sigortacılık odaklı
            st.subheader("Hasar Analizi")
            col_hasar1, col_hasar2 = st.columns(2)
            with col_hasar1:
                st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni_kaynakli', 'N/A')}")
                st.warning(f"**Etkilenen Değerler:** {report.get('etkilenen_degerler', 'N/A')}")
            with col_hasar2:
                st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")

            st.subheader("Operasyonel Etki ve Müdahale")
            col_op1, col_op2 = st.columns(2)
            with col_op1:
                 st.info(f"**İş Durması Etkisi:** {report.get('is_durmasi_etkisi', 'N/A')}")
                 st.info(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            with col_op2:
                 st.success(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
            
            with st.expander("Olay Yeri Haritası ve Çevre Analizi", expanded=True):
                st.info(f"**Metinsel Çevre Analizi:** {report.get('cevre_etkisi_metinsel', 'Haber metninde çevreye etki ile ilgili bir bilgi tespit edilemedi.')}")
                coords = report.get('tahmini_koordinat', {})
                lat, lon = coords.get('lat'), coords.get('lon')
                if lat and lon:
                    try:
                        m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                        folium.Marker([float(lat), float(lon)], 
                                      popup=f"<b>{report.get('tesis_adi')}</b>", 
                                      icon=folium.Icon(color='red', icon='fire')).add_to(m)
                        
                        neighbors = report.get('komsu_tesisler', [])
                        for neighbor in neighbors:
                            if neighbor.get('lat') and neighbor.get('lng'):
                                folium.Marker([neighbor['lat'], neighbor['lng']], 
                                              popup=f"<b>{neighbor['tesis_adi']}</b><br>{neighbor.get('adres', '')}", 
                                              tooltip=neighbor['tesis_adi'],
                                              icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                        
                        folium_static(m, height=400)

                        if neighbors:
                            st.write("Yakın Çevredeki Tesisler (1km - Google Maps Verisi)")
                            st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])

                    except (ValueError, TypeError):
                        st.warning("Rapor koordinatları geçersiz, harita çizilemiyor.")
                else:
                    st.info("Rapor, harita çizimi için koordinat bilgisi içermiyor.")
