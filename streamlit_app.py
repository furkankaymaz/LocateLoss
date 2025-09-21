# ==============================================================================
#  Nihai MVP (v41.0): RSS Kaynağı + Akıllı Google Arama Simülasyonu
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

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Akıllı Hasar Simülasyonu")
st.title("🛰️ Akıllı Hasar Simülasyon Motoru")

grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY") # Harita için gerekli
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900) # Haberleri 15 dakikada bir yenile
def get_latest_events_from_rss():
    """Google News RSS'ten en son olay adaylarını başlık ve özetleriyle çeker."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []
        
        articles = []
        for entry in feed.entries[:15]: # En son 15 haberi al
            summary_text = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            articles.append({
                "headline": entry.title.split(" - ")[0],
                "summary": summary_text,
                "url": entry.link
            })
        return articles
    except Exception as e:
        st.error(f"RSS akışı okunurken hata: {e}")
        return []

@st.cache_data(ttl=3600)
def analyze_event_with_simulation(_client, headline, summary):
    """Verilen başlık ve özeti kullanarak Google Arama simülasyonu ile tesisi bulur ve raporlar."""
    prompt = f"""
    Sen, internetin tamamını taramış ve hafızasına kaydetmiş elit bir istihbarat analistisin.

    GÖREV: Sana verilen haber başlığı ve özetindeki ipuçlarını kullanarak bir **Google Arama simülasyonu** yapacaksın. Bu simülasyonla, olayın yaşandığı tesisin **ticari unvanını** bulmayı ve olayı sigortacılık perspektifiyle raporlamayı hedefliyorsun.

    SANA VERİLEN İPUÇLARI:
    - BAŞLIK: "{headline}"
    - ÖZET: "{summary}"

    DÜŞÜNCE SÜRECİN (ADIM ADIM):
    1.  **Arama Sorgusu Oluştur:** İpuçlarından en etkili Google arama sorgusunu oluştur (örn: "Gebze Kömürcüler OSB boya fabrikası yangın").
    2.  **Arama Sonuçlarını Değerlendir:** Hafızandaki bilgilere dayanarak, bu arama sonucunda karşına çıkacak haber başlıklarını ve snippet'leri düşün. Hangi haber kaynaklarının (AA, DHA, yerel basın) hangi şirket ismini verdiğini analiz et.
    3.  **Teyit Et:** Farklı kaynakların aynı ismi verip vermediğini kontrol ederek en olası ticari unvanı bul.
    4.  **Raporla:** Tüm bu simülasyon sürecinden elde ettiğin bilgileri, aşağıdaki JSON formatına eksiksiz bir şekilde dök.

    JSON ÇIKTISI (SADECE JSON VER, AÇIKLAMA EKLEME):
    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan.",
      "kanit": "Bu isme nasıl ulaştığının açıklaması. Örn: 'Google'da yapılan '...' aramasında, AA ve DHA kaynakları ABC Kimya A.Ş. ismini teyit etmektedir.'",
      "sehir_ilce": "Olayın yaşandığı yer.",
      "olay_ozeti": "Olayın fiziksel boyutu, nedeni ve sonuçları.",
      "guncel_durum": "Üretim durması, müdahale durumu vb. en son bilgiler.",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}}
    }}
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.1
        )
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        st.error(f"AI, geçerli bir JSON formatı üretemedi. Ham yanıt: {content}")
        return None
    except Exception as e:
        st.error(f"AI Analizi sırasında hata oluştu: {e}")
        return None

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Son Olaylar")
    with st.spinner("Güncel haberler taranıyor..."):
        events = get_latest_events_from_rss()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        event_map = {f"{event['headline']}": event for event in events}
        selected_headline = st.radio(
            "Analiz için bir olay seçin:",
            event_map.keys()
        )
        st.session_state.selected_event = event_map[selected_headline]

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' in st.session_state:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        st.caption(f"Kaynak: [{event['url']}]({event['url']})")
        st.markdown(f"**Haber Özeti:** *{event['summary']}*")
        
        if st.button("🤖 Bu Olayı Analiz Et", type="primary", use_container_width=True):
            if not client:
                st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin.")
            else:
                with st.spinner("AI, Google Arama simülasyonu ile istihbarat topluyor..."):
                    report = analyze_event_with_simulation(client, event['headline'], event['summary'])
                    st.session_state.report = report
    
    if 'report' in st.session_state and st.session_state.report:
        report = st.session_state.report
        st.markdown("---")
        st.subheader(f"Rapor: {report.get('tesis_adi', 'Teyit Edilemedi')}")
        st.info(f"**Kanıt Zinciri:** {report.get('kanit', 'N/A')}")
        
        st.success(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
        st.warning(f"**Olay Özeti:** {report.get('olay_ozeti', 'N/A')}")
        
        # Harita Kısmı
        coords = report.get('tahmini_koordinat', {})
        lat, lon = coords.get('lat'), coords.get('lon')
        if lat and lon and google_api_key:
            try:
                m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                folium.Marker([float(lat), float(lon)], 
                              popup=f"<b>{report.get('tesis_adi')}</b>", 
                              icon=folium.Icon(color='red', icon='fire')).add_to(m)
                st.subheader("Olay Yeri Haritası")
                folium_static(m, height=300)
            except (ValueError, TypeError):
                st.warning("Rapor koordinatları geçersiz, harita çizilemiyor.")
