# ==============================================================================
#  NİHAİ KOD (v44.0): Stabil Tesis Tespiti ve Yenilenmiş Arayüz
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

grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_latest_events_from_rss_deduplicated():
    """Google News RSS'ten en son olayları çeker, tarihe göre sıralar ve akıllıca tekilleştirir."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı"'
    q = f'({locations}) AND ({events})'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []
        
        # ÖNCE: Haberleri en yeniden en eskiye doğru sırala
        sorted_entries = sorted(feed.entries, key=lambda e: getattr(e, 'published_parsed', time.gmtime(0)), reverse=True)
        
        unique_articles = []
        seen_headlines = []
        
        # SONRA: Sıralanmış liste üzerinden tekilleştirme yap
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
def analyze_event_with_stable_engine(_client, headline, summary):
    """
    Tesis adını bulmaya odaklanmış, "Düşünce Süreci" ve "Güven Skoru" içeren stabil analiz motoru.
    """
    prompt = f"""
    Sen, internetin tamamını taramış elit bir istihbarat analistisin. Ana görevin, sana verilen ipuçlarından yola çıkarak olayın yaşandığı TESİSİN TİCARİ UNVANINI bulmaktır.

    SANA VERİLEN İPUÇLARI:
    - BAŞLIK: "{headline}"
    - ÖZET: "{summary}"

    DÜŞÜNCE SÜRECİN (ADIM ADIM):
    1.  **Arama Sorgusu Oluştur:** İpuçlarından en etkili Google arama sorgusunu zihninde oluştur (örn: 'Gebze Kömürcüler OSB boya fabrikası yangın').
    2.  **Arama Sonuçlarını Değerlendir:** Hafızandaki bilgilere dayanarak, bu arama sonucunda karşına çıkacak haber başlıklarını ve snippet'leri düşün. Hangi güvenilir haber kaynaklarının (AA, DHA, yerel basın, resmi kurumlar) hangi şirket ismini verdiğini analiz et.
    3.  **Teyit ve Güven Skoru Ata:** Farklı ve bağımsız kaynakların aynı ismi verip vermediğini kontrol et. Teyit seviyesine göre 1 (zayıf) ile 5 (çok güçlü) arasında bir güven skoru belirle.
    4.  **Raporla:** Tüm bu simülasyon sürecinden elde ettiğin kesinleşmiş bilgileri, aşağıdaki JSON formatına eksiksiz bir şekilde dök.

    JSON ÇIKTISI (SADECE JSON VER, AÇIKLAMA EKLEME):
    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan.",
      "guven_skoru": "1-5 arası bir sayı.",
      "kanit_zinciri": "Bu isme nasıl ulaştığının ve hangi kaynakların teyit ettiğinin detaylı açıklaması. Güven skorunun nedenini de belirt.",
      "sehir_ilce": "Olayın yaşandığı yer.",
      "olay_ozeti": "Olayın ne olduğu, fiziksel boyutu, nedeni ve sonuçları hakkında kısa ve net özet.",
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

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    if not all([api_key, lat, lon]): return []
    try:
        keywords = quote("fabrika|depo|sanayi|tesis|lojistik|antrepo")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius=1000&keyword={keywords}&key={api_key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        results = response.json().get('results', [])
        return [{
            "tesis_adi": p.get('name'), "adres": p.get('vicinity'), 
            "lat": p.get('geometry',{}).get('location',{}).get('lat'),
            "lng": p.get('geometry',{}).get('location',{}).get('lng')
        } for p in results[:10]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}")
        return []

# ------------------------------------------------------------------------------
# 3. YENİLENMİŞ STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Son Olaylar")
    with st.spinner("Güncel ve tekil haberler taranıyor..."):
        events = get_latest_events_from_rss_deduplicated()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        # YENİ ARAYÜZ: Her haber için tıklanabilir kartlar
        for event in events:
            with st.container(border=True):
                st.markdown(f"**{event['headline']}**")
                if st.button("Bu Haberi Seç", key=event['url'], use_container_width=True):
                    st.session_state.selected_event = event
                    # Raporu temizle
                    if 'report' in st.session_state:
                        del st.session_state.report
                    st.rerun()

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' not in st.session_state:
        st.info("Lütfen sol panelden analiz etmek için bir haber seçin.")
    else:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        st.caption(f"Kaynak: [{event['url']}]({event['url']})")
        
        if st.button("🤖 Bu Olayı Analiz Et", type="primary", use_container_width=True):
            if not client:
                st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin.")
            else:
                with st.spinner("AI, Google Arama simülasyonu ile istihbarat topluyor..."):
                    report = analyze_event_with_stable_engine(client, event['headline'], event['summary'])
                    if report and report.get('tahmini_koordinat'):
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
            
            st.success(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
            st.warning(f"**Olay Özeti:** {report.get('olay_ozeti', 'N/A')}")
            
            with st.expander("Olay Yeri Haritası ve Çevre Analizi", expanded=True):
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
