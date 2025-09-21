# ==============================================================================
#  Gelişmiş MVP (v43.0): Sigortacılık Odaklı Derin Analiz ve Kanıt Zinciri
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

# API Anahtarlarını Streamlit Secrets'tan güvenli bir şekilde al
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")

# OpenAI istemcisini yalnızca API anahtarı varsa başlat
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. YARDIMCI FONKSİYONLAR
# ------------------------------------------------------------------------------

def refine_headline(title):
    """Haber başlıklarını temizler ve daha profesyonel bir formata getirir."""
    # Kaynakları ve genel ifadeleri (örn: "Son Dakika:") temizle
    title = re.sub(r'^\s*.*?(:\s*|\s*-\s*)', '', title)
    title = re.sub(r'^(Son Dakika|GÜNCELLEME|FLAŞ|HABERİ)\s*[:\-]?\s*', '', title, flags=re.IGNORECASE)
    title = title.split(' - ')[0].strip()
    return title.capitalize() if title else "Başlıksız Olay"

# ------------------------------------------------------------------------------
# 3. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)  # Önbelleği 15 dakikada bir yenile
def get_latest_events_from_rss_deduplicated():
    """Google News RSS'ten en son olayları çeker ve akıllı tekilleştirme uygular."""
    locations = '"fabrika" OR "sanayi" OR "OSB" OR "liman" OR "depo" OR "tesis"'
    events = '"yangın" OR "patlama" OR "kaza" OR "sızıntı" OR "çökme"'
    q = f'({locations}) AND ({events})'
    # Son 3 günü tara
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return []
        
        event_clusters = {}
        for entry in feed.entries:
            # Başlığı temizle ve profesyonel hale getir
            clean_title = refine_headline(entry.title)
            
            # Benzer bir olay kümesi var mı diye kontrol et
            found_cluster = None
            for key_title in event_clusters:
                # token_set_ratio, kelime sırasından bağımsız olarak daha iyi bir eşleşme sağlar
                if fuzz.token_set_ratio(clean_title, key_title) > 85:
                    found_cluster = key_title
                    break
            
            summary_text = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            article_data = {"headline": entry.title, "summary": summary_text, "url": entry.link}

            if found_cluster:
                # Mevcut kümeye ekle. En detaylı özeti ve başlığı koru.
                if len(summary_text) > len(event_clusters[found_cluster]['summary']):
                    event_clusters[found_cluster]['summary'] = summary_text
                    event_clusters[found_cluster]['url'] = entry.link
                event_clusters[found_cluster]['articles'].append(article_data)
            else:
                # Yeni bir olay kümesi oluştur
                event_clusters[clean_title] = {'summary': summary_text, 'url': entry.link, 'articles': [article_data]}

        # UI için son listeyi oluştur
        final_list = [{"headline": title, "summary": data['summary'], "url": data['url']} for title, data in event_clusters.items()]
        
        return final_list[:20]  # En fazla 20 tekil olay göster

    except Exception as e:
        st.error(f"RSS akışı okunurken hata oluştu: {e}")
        return []

@st.cache_data(ttl=3600)
def analyze_event_with_insurance_perspective(_client, headline, summary):
    """
    Yapay zekayı bir sigorta eksperi gibi çalıştırarak olayı analiz eder,
    kanıt zinciri oluşturur ve detaylı bir JSON raporu hazırlar.
    """
    # YENİ VE GELİŞTİRİLMİŞ PROMPT: Sigortacılık odaklı, kanıt talep eden ve detaylı.
    prompt = f"""
    SENARYO: Sen, sigorta şirketleri için çalışan, A-seviye bir hasar istihbarat analistisin. Görevin, bir haber kırıntısından yola çıkarak, olayı bir sigorta eksperinin gözüyle, kanıtlara dayalı ve detaylı bir şekilde analiz etmektir. Halüsinasyon görmen kesinlikle yasaktır. Her bilgiyi, simüle ettiğin arama sonuçlarından (verilen haber metninden) çıkardığın kanıtlara dayandırmalısın.

    GÖREV: Sana verilen haber başlığı ve özetini kullanarak, internette çok adımlı bir araştırma simülasyonu yap. Amacın, olayı sigortacılık açısından en ince detayına kadar aydınlatan ve tüm iddialarını kanıtlarla destekleyen bir JSON raporu oluşturmak.

    SANA VERİLEN İPUÇLARI:
    - BAŞLIK: "{headline}"
    - ÖZET: "{summary}"

    JSON ÇIKTI FORMATI (SADECE JSON VER, KESİNLİKLE AÇIKLAMA EKLEME):
    {{
      "tesis_adi": "Simülasyon sonucu bulunan en olası ticari unvan. Bulamazsan 'Teyit Edilemedi' yaz.",
      "guven_skoru": "1-5 arası bir sayı. 5, resmi bir kaynak tarafından (itfaiye, valilik) doğrudan teyit edilmiş demektir.",
      "kanit": "Bu isme nasıl ulaştığının ve hangi kaynakların teyit ettiğinin kanıta dayalı açıklaması. Örn: 'Haberde geçen 'Dilovası OSB' ve 'kimya tesisi' ifadeleri ile yapılan aramada, DHA ve AA'nın haberlerinde tesisin adı 'ABC Kimya A.Ş.' olarak geçmektedir.'",
      "sehir_ilce": "Olayın yaşandığı yer.",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}},
      "hasar_detaylari": {{
        "baslangic_nedeni": "Haber metninden çıkarılan neden (örn: elektrik kontağı, kazan patlaması) veya 'Belirtilmemiş'.",
        "etkilenen_alanlar": "Tesisin hangi bölümlerinin etkilendiği (örn: üretim bandı, depo bölümü, idari bina) veya 'Belirtilmemiş'.",
        "hasar_goren_varliklar": "Hangi makine, teçhizat, hammadde veya mamul ürünlerin zarar gördüğü (örn: 5 adet CNC makinesi, 20 ton polimer hammadde) veya 'Belirtilmemiş'.",
        "yayilma_ve_kontrol": "Hasarın nasıl yayıldığı ve kontrol altına alındığı (örn: çatıya sıçradı, itfaiyenin 2 saatlik müdahalesiyle söndürüldü) veya 'Belirtilmemiş'.",
        "tahmini_maddi_boyut": "Haberde geçen herhangi bir parasal değer veya 'Belirtilmemiş'."
      }},
      "cevre_tesislere_etki": "Haberde, olayın komşu tesislere sıçradığına, dumandan etkilendiğine veya çevresel bir tehlike oluşturduğuna dair bir ipucu var mı? Örn: 'Yoğun dumanın yakındaki Gıda Toptancıları Sitesi'ni etkilediği belirtildi.' Bilgi yoksa, 'Haberde çevre tesislere bir etki belirtilmemiştir.' yaz.",
      "guncel_durum": "Soğutma çalışmaları, üretimin durup durmadığı gibi en son bilgiler.",
      "sigorta_perspektifi": "Bu olayın potansiyel sigorta talepleri neler olabilir? Yangın (All Risks), Makine Kırılması, Kar Kaybı, 3. Şahıs Sorumluluk gibi potansiyel talepleri ve nedenlerini bir uzman gibi analiz et."
    }}
    """
    try:
        # Daha karmaşık ve detaylı analizler için 'pro' modelini kullan
        response = _client.chat.completions.create(model="grok-1.5-pro-latest", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
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
    """Google Places API ile olay yeri çevresindeki endüstriyel tesisleri bulur."""
    if not all([api_key, lat, lon]): return []
    try:
        # Arama yarıçapı artırıldı ve anahtar kelimeler genişletildi
        keywords = quote("fabrika|depo|sanayi|tesis|lojistik|antrepo|üretim")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius=1500&keyword={keywords}&key={api_key}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        results = response.json().get('results', [])
        
        neighbors = [{
            "tesis_adi": p.get('name'), 
            "adres": p.get('vicinity'), 
            "lat": p.get('geometry', {}).get('location', {}).get('lat'),
            "lng": p.get('geometry', {}).get('location', {}).get('lng')
        } for p in results[:10]] # En fazla 10 komşu tesis
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API ile komşu tesisler çekilirken hata oluştu: {e}")
        return []

# ------------------------------------------------------------------------------
# 4. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------
col1, col2 = st.columns([1, 2], gap="large")

with col1:
    st.header("📰 Son Olaylar")
    with st.spinner("Güncel ve tekil olaylar taranıyor..."):
        events = get_latest_events_from_rss_deduplicated()
    
    if not events:
        st.warning("Analiz edilecek yeni bir olay bulunamadı.")
    else:
        # Daha okunaklı bir liste için sadece başlıkları al
        event_headlines = [event['headline'] for event in events]
        event_map = {event['headline']: event for event in events}
        selected_headline = st.radio("Analiz için bir olay seçin:", event_headlines, label_visibility="collapsed")
        st.session_state.selected_event = event_map[selected_headline]

with col2:
    st.header("📝 Analiz Paneli")
    if 'selected_event' in st.session_state:
        event = st.session_state.selected_event
        st.subheader(event['headline'])
        st.caption(f"Kaynak Haber: [Link]({event['url']})")
        st.markdown(f"**Özet:** *{event['summary']}*")
        
        if st.button("🤖 Bu Olayı Derinlemesine Analiz Et", type="primary", use_container_width=True):
            if not client or not google_api_key:
                st.error("Lütfen Grok ve Google API anahtarlarını Streamlit Secrets'a ekleyin.")
            else:
                with st.spinner("AI, sigorta eksperi gibi olayı analiz ediyor ve kanıt topluyor..."):
                    report = analyze_event_with_insurance_perspective(client, event['headline'], event['summary'])
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
            st.metric(label="Güven Skoru", value=f"{score}/5", help="AI'ın bu tespiti yaparkenki güven seviyesi (5=Çok Güçlü)")

        st.info(f"**Kanıt Zinciri & Teyit:** {report.get('kanit', 'N/A')}")
        st.success(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")

        st.subheader("🛡️ Sigorta Perspektifi")
        st.markdown(report.get('sigorta_perspektifi', 'Analiz bekleniyor...'))

        with st.expander("Detaylı Hasar Analizi", expanded=True):
            hasar = report.get('hasar_detaylari', {})
            if hasar:
                st.markdown(f"""
                - **Başlangıç Nedeni:** {hasar.get('baslangic_nedeni', 'N/A')}
                - **Etkilenen Alanlar:** {hasar.get('etkilenen_alanlar', 'N/A')}
                - **Hasar Gören Varlıklar:** {hasar.get('hasar_goren_varliklar', 'N/A')}
                - **Yayılma ve Kontrol:** {hasar.get('yayilma_ve_kontrol', 'N/A')}
                - **Tahmini Maddi Boyut:** {hasar.get('tahmini_maddi_boyut', 'N/A')}
                """)
            else:
                st.warning("Detaylı hasar analizi verisi bulunamadı.")

        with st.expander("Olay Yeri Haritası ve Çevresel Etki", expanded=True):
            st.warning(f"**Çevre Tesislere Etki:** {report.get('cevre_tesislere_etki', 'N/A')}")
            coords = report.get('tahmini_koordinat', {})
            lat, lon = coords.get('lat'), coords.get('lon')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                    # Ana olay pini
                    folium.Marker([float(lat), float(lon)], 
                                  popup=f"<b>{report.get('tesis_adi')}</b>", 
                                  icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    
                    # Komşu tesis pinleri
                    neighbors = report.get('komsu_tesisler', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker([neighbor['lat'], neighbor['lng']], 
                                          popup=f"<b>{neighbor['tesis_adi']}</b><br>{neighbor.get('adres', '')}", 
                                          tooltip=neighbor['tesis_adi'],
                                          icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    
                    folium_static(m, height=400)
                    
                    if neighbors:
                        st.write(f"Yakın Çevredeki Tesisler ({len(neighbors)} adet bulundu)")
                        st.dataframe(pd.DataFrame(neighbors)[['tesis_adi', 'adres']])

                except (ValueError, TypeError):
                    st.warning("Rapor koordinatları geçersiz, harita çizilemiyor.")
            else:
                st.info("Rapor, harita çizimi için koordinat bilgisi içermiyor.")
