# ==============================================================================
#  Gelişmiş MVP (v42.0): Güven Skoru, Tekilleştirme ve Çevre Analizi
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
st.set_page_config(layout="wide", page_title="Gelişmiş Hasar Analizi")
st.title("🛰️ Gelişmiş Hasar İstihbarat Motoru")

grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_latest_events_from_rss_deduplicated():
    """Google News RSS'ten en son olayları çeker ve benzer başlıkları tekilleştirir."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []
        
        unique_articles = []
        seen_headlines = []
        
        # GÜNCELLEME: Akıllı Tekilleştirme
        for entry in feed.entries:
            headline = entry.title.split(" - ")[0]
            
            # Daha önce eklenmiş bir başlığa çok benziyorsa atla
            if any(fuzz.ratio(headline, seen_headline) > 85 for seen_headline in seen_headlines):
                continue

            summary_text = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            unique_articles.append({
                "headline": headline,
                "summary": summary_text,
                "url": entry.link
            })
            seen_headlines.append(headline)

        return unique_articles[:15] # En fazla 15 tekil haber
    except Exception as e:
        st.error(f"RSS akışı okunurken hata: {e}")
        return []

@st.cache_data(ttl=3600)
def analyze_event_with_simulation(_client, headline, summary):
    """Verilen bilgilere dayanarak Google Arama simülasyonu yapar, Güven Skoru üretir ve raporlar."""
    # GÜNCELLEME: Prompt, Güven Skoru ve Çapraz Doğrulama talimatları ile zenginleştirildi
    prompt = f"""
    Sen, internetin tamamını taramış elit bir istihbarat analistisin.

    GÖREV: Sana verilen haber başlığı ve özetindeki ipuçlarını kullanarak bir **Google Arama simülasyonu** yapacaksın. Bu simülasyonla, olayın yaşandığı tesisin **ticari unvanını** bulmayı ve olayı sigortacılık perspektifiyle raporlamayı hedefliyorsun.

    SANA VERİLEN İPUÇLARI:
    - BAŞLIK: "{headline}"
    - ÖZET: "{summary}"

    KRİTİK TALİMATLAR:
    1.  **Çapraz Doğrulama:** Arama simülasyonunda, bulduğun şirket isminin birden fazla bağımsız kaynak (örn: ulusal bir haber ajansı VE yerel bir gazete VEYA X'teki resmi bir hesap) tarafından teyit edilip edilmediğini kontrol et.
    2.  **Güven Skoru Ata:** Teyit seviyesine göre, bulduğun "tesis_adi" bilgisine 1 (çok zayıf) ile 5 (çok güçlü) arasında bir "guven_skoru" ata.
    3.  **Kanıt Zinciri Oluştur:** "kanit" alanında, isme nasıl ulaştığını, hangi kaynakların teyit ettiğini ve güven skorunun nedenini açıkla.
    4.  **Resmi Kaynaklara Öncelik Ver:** Simülasyonunda, özellikle X'teki resmi kurumların (itfaiye, valilik) veya güvenilir gazetecilerin paylaşımlarına öncelik ver.

    JSON ÇIKTISI (SADECE JSON VER, AÇIKLAMA EKLEME):
    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan.",
      "guven_skoru": "1-5 arası bir sayı.",
      "kanit": "Bu isme nasıl ulaştığının ve hangi kaynakların teyit ettiğinin detaylı açıklaması.",
      "sehir_ilce": "Olayın yaşandığı yer.",
      "olay_ozeti": "Olayın fiziksel boyutu, nedeni ve sonuçları.",
      "guncel_durum": "Üretim durması, müdahale durumu vb. en son bilgiler.",
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

# YENİ: Google Places API ile komşu tesisleri bulan fonksiyon
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        # Anahtar kelimeler URL uyumlu hale getirildi ve radius artırıldı
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
        } for p in results[:10]] # En fazla 10 komşu tesis
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
        # GÜNCELLEME: Tekilleştirilmiş haberleri çeken fonksiyon çağrılıyor
        events = get_latest_events_from_rss_deduplicated()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        event_map = {f"{event['headline']}": event for event in events}
        selected_headline = st.radio("Analiz için bir olay seçin:", event_map.keys())
        st.session_state.selected_event = event_map[selected_headline]

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' in st.session_state:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        st.caption(f"Kaynak: [{event['url']}]({event['url']})")
        st.markdown(f"**Haber Özeti:** *{event['summary']}*")
        
        if st.button("🤖 Bu Olayı Analiz Et", type="primary", use_container_width=True):
            if not client or not google_api_key:
                st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin.")
            else:
                with st.spinner("AI, Google Arama simülasyonu ile istihbarat topluyor..."):
                    report = analyze_event_with_simulation(client, event['headline'], event['summary'])
                    # GÜNCELLEME: Rapor başarılıysa, komşu tesisleri de çek
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
            # YENİ: Güven Skoru göstergesi
            score = report.get('guven_skoru', 0)
            st.metric(label="Güven Skoru", value=f"{score}/5", help="AI'ın bu tespiti yaparkenki güven seviyesi (1=Zayıf, 5=Çok Güçlü)")

        st.info(f"**Kanıt Zinciri:** {report.get('kanit', 'N/A')}")
        
        st.success(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
        st.warning(f"**Olay Özeti:** {report.get('olay_ozeti', 'N/A')}")
        
        # GÜNCELLEME: Harita artık komşu tesisleri de içeriyor
        with st.expander("Olay Yeri Haritası ve Çevre Analizi", expanded=True):
            coords = report.get('tahmini_koordinat', {})
            lat, lon = coords.get('lat'), coords.get('lon')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                    # Ana olay pini (Kırmızı)
                    folium.Marker([float(lat), float(lon)], 
                                  popup=f"<b>{report.get('tesis_adi')}</b>", 
                                  icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    
                    # Komşu tesis pinleri (Mavi)
                    neighbors = report.get('komsu_tesisler', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker([neighbor['lat'], neighbor['lng']], 
                                          popup=f"<b>{neighbor['tesis_adi']}</b><br>{neighbor.get('adres', '')}", 
                                          tooltip=neighbor['tesis_adi'],
                                          icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    
                    folium_static(m, height=400)

                    # YENİ: Komşu tesisler tablosu
                    if neighbors:
                        st.write("Yakın Çevredeki Tesisler (1km)")
                        st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])

                except (ValueError, TypeError):
                    st.warning("Rapor koordinatları geçersiz, harita çizilemiyor.")
            else:
                st.info("Rapor, harita çizimi için koordinat bilgisi içermiyor.")
