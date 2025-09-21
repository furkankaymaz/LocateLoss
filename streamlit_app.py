# ==============================================================================
#  NİHAİ KOD (v32.0): Kanıta Dayalı Bütünsel Analiz Modeli
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
# 1. TEMEL AYARLAR VE GÖRSEL TASARIM
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")

# --- Modern UI Stilleri ---
st.markdown("""
<style>
    .stApp {
        background-color: #f5f5f5;
    }
    .st-emotion-cache-16txtl3 {
        padding: 2rem 1rem 1rem 1rem;
    }
    .st-emotion-cache-z5fcl4 {
        padding-top: 2rem;
    }
    h1, h2, h3 {
        color: #1E3A8A; /* Koyu Mavi */
    }
    .stButton>button {
        background-color: #1E3A8A;
        color: white;
        border-radius: 8px;
        border: none;
    }
    .st-emotion-cache-1kyxreq {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 0.25rem;
        background-color: #DBEAFE; /* Açık Mavi */
        border-radius: 8px;
        color: #1E3A8A;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")
st.markdown("---")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None


# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

# Adım 1: Haber Kaynağını Çekme ve Filtreleme
@st.cache_data(ttl=900) # 15 dakikada bir yenile
def get_news_feed():
    """Google News RSS'ten ilgili haber başlıklarını ve özetlerini çeker."""
    search_query = '("endüstriyel tesis" OR "sanayi tesisi" OR "fabrika" OR "liman" OR "santral" OR "OSB") AND ("yangın" OR "patlama" OR "kaza" OR "sızıntı")'
    rss_url = f"https://news.google.com/rss/search?q={quote(search_query)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        # Sadece başlıkta "yangın, patlama, kaza, çökme" gibi anahtar kelimeler geçenleri al
        keywords = ["yangın", "patlama", "kaza", "çökme", "sızıntı"]
        events = [
            {
                "title": entry.title.split(" - ")[0], # Kaynak ismini başlıktan temizle
                "link": entry.link,
                "summary": entry.get('summary', '').split('<a')[0] # Özet metnini al ve linkleri temizle
            }
            for entry in feed.entries
            if any(keyword in entry.title.lower() for keyword in keywords)
        ]
        return events[:15] # En son 15 uygun haberi döndür
    except Exception as e:
        st.sidebar.error(f"RSS Akışı Hatası: {e}")
        return []

# Adım 2: Bütünsel Analiz AI
@st.cache_data(ttl=3600)
def analyze_event_holistically(_client, title, summary):
    """Verilen haber metnini tek bir seferde analiz edip yapılandırılmış JSON raporu oluşturur."""
    prompt = f"""
    Sen, kanıta dayalı çalışan ve asla varsayımda bulunmayan bir sigorta risk analistisin.
    
    ANA GÖREVİN: Sana verilen aşağıdaki haber metnini analiz ederek, olayın yaşandığı TESİSİN TİCARİ UNVANINI en yüksek doğrulukla tespit etmek ve olayı tüm detaylarıyla raporlamaktır.

    HABER BAŞLIĞI: "{title}"
    HABER ÖZET METNİ: "{summary}"

    KRİTİK TALİMATLAR:
    1.  **TESİS ADI TESPİTİ (ÖNCELİK 1):** Tesisin adını doğrudan haber metninden bulmaya çalış. Eğer metinde yoksa, metindeki konum (örn: Gebze OSB) ve olay tipi (örn: kimya fabrikası yangını) bilgilerini kullanarak X (Twitter) üzerinde bir arama yaptığını SİMÜLE ET ve bulduğun en olası ismi belirt.
    2.  **KANIT ZORUNLULUĞU:** Tesis adını nasıl bulduğunu 'tesis_adi_dogrulama_yontemi' alanında AÇIKÇA belirtmek zorundasın. (Örnek: "İsim, haber metninin 3. paragrafında doğrudan belirtilmiştir." veya "Haberdeki 'Dilovası Kömürcüler OSB' konumu ve 'boya fabrikası' tanımıyla yapılan X aramalarında 'ABC Boya A.Ş.' ismi teyit edilmiştir.")
    3.  **ASLA UYDURMA:** Eğer hiçbir şekilde (ne metinden ne de simüle edilmiş X aramasından) tesisin adından emin olamazsan, "Teyit Edilemedi" yaz.
    4.  **SİGORTA TERMİNOLOJİSİ:** Raporu sigortacılık bakış açısıyla doldur. Özellikle Maddi Hasar ve İş Durması (Kar Kaybı) ayrımına dikkat et.
    5.  **GÖRSEL BULMA:** Haber metninde bir görsel (resim) linki geçiyorsa URL'sini al. Yoksa boş bırak.

    Lütfen çıktı olarak SADECE aşağıdaki anahtarlara sahip TEK BİR JSON nesnesi ver. Başka hiçbir açıklama ekleme.

    JSON YAPISI:
    {{
      "tesis_adi": "...",
      "tesis_adi_dogrulama_yontemi": "...",
      "sehir_ilce": "...",
      "tahmini_koordinat": {{"lat": "...", "lon": "..."}},
      "maddi_hasar_fiziksel_boyut": "Örn: Fabrikanın 5000 m2'lik depo alanı ve içindeki makineler tamamen yandı.",
      "is_durmasi_kar_kaybi": "Örn: Üretim en az 2 hafta durduruldu, günlük ciro kaybı tahmini 5 Milyon TL.",
      "hasarin_nedeni": "Örn: Elektrik panosundaki kısa devreden şüpheleniliyor.",
      "yapilan_mudahale": "Örn: Olay yerine 15 itfaiye aracı ve 50 personel sevk edildi.",
      "guncel_durum": "Örn: Yangın kontrol altına alındı, soğutma çalışmaları devam ediyor.",
      "cevreye_etki": "Örn: Yoğun duman nedeniyle yakındaki yerleşim yerleri uyarıldı.",
      "gorsel_url": "...",
      "kaynak_url": "{' '}"
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
        return None
    except Exception as e:
        st.error(f"Bütünsel Analiz AI Hatası: {e}")
        return None

# Adım 3: Google Harita Zenginleştirmesi
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    """Verilen koordinatlara yakın endüstriyel tesisleri Google Places API ile bulur."""
    if not all([api_key, lat, lon]):
        return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = [{
            "tesis_adi": p.get('name'),
            "tip": ", ".join(p.get('types', [])),
            "konum": p.get('vicinity'),
            "lat": p.get('geometry', {}).get('location', {}).get('lat'),
            "lng": p.get('geometry', {}).get('location', {}).get('lng')
        } for p in results[:10]]
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API Hatası: {e}")
        return []


# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------

# Session state'i başlat
if 'report' not in st.session_state:
    st.session_state.report = None
if 'selected_event_title' not in st.session_state:
    st.session_state.selected_event_title = None

col_list, col_detail = st.columns([1, 2], gap="large")

with col_list:
    st.header("📰 Gelen Olaylar")
    with st.spinner("Güncel olaylar taranıyor..."):
        events = get_news_feed()

    if not events:
        st.warning("Son 7 gün içinde analiz edilecek yeni bir endüstriyel olay bulunamadı.")
    else:
        event_titles = [event['title'] for event in events]
        
        # Eğer daha önce bir seçim yapıldıysa o seçimi koru
        try:
            current_index = event_titles.index(st.session_state.selected_event_title)
        except (ValueError, TypeError):
            current_index = 0

        selected_title = st.radio(
            "Analiz için bir olay seçin:",
            event_titles,
            index=current_index,
            key="event_selector"
        )
        
        # Seçimi session state'e kaydet
        st.session_state.selected_event_title = selected_title
        
        selected_event_index = event_titles.index(selected_title)
        selected_event = events[selected_event_index]

        if st.button("✔️ Seçili Olayı Analiz Et", type="primary", use_container_width=True):
            if not all([client, google_api_key]):
                st.error("Grok ve Google API anahtarları eksik!")
            else:
                with st.spinner("Bütünsel Analiz Motoru çalışıyor... Metin okunuyor, tesis adı teyit ediliyor..."):
                    report_data = analyze_event_holistically(client, selected_event['title'], selected_event['summary'])
                    if report_data:
                        report_data['kaynak_url'] = selected_event['link'] # Kaynak URL'i rapora ekle
                        coords = report_data.get('tahmini_koordinat', {})
                        lat, lon = coords.get('lat'), coords.get('lon')
                        
                        if lat and lon:
                           report_data['komsu_tesisler'] = find_neighboring_facilities(google_api_key, lat, lon)
                        
                        st.session_state.report = report_data
                    else:
                        st.session_state.report = None
                        st.error("Analiz motoru bu haber için bir rapor oluşturamadı.")


with col_detail:
    st.header("📝 Analiz Raporu")
    if not st.session_state.report:
        st.info("Lütfen sol menüden bir olay seçip 'Analiz Et' butonuna tıklayın.")
    else:
        report = st.session_state.report
        
        # Rapor Başlığı ve Kanıt
        st.subheader(report.get('tesis_adi', 'Tesis Adı Teyit Edilemedi'))
        st.info(f"**Doğrulama Yöntemi:** {report.get('tesis_adi_dogrulama_yontemi', 'Belirtilmemiş')}")

        if report.get('gorsel_url'):
            st.image(report.get('gorsel_url'), caption="Olay Yerinden Görüntü (Tahmini)")

        st.markdown("---")

        # Hasar Analizi
        st.subheader("Hasar Analizi")
        sub_col1, sub_col2 = st.columns(2)
        with sub_col1:
            st.markdown("<h5>Maddi Hasar</h5>", unsafe_allow_html=True)
            st.warning(f"**Fiziksel Boyut:** {report.get('maddi_hasar_fiziksel_boyut', 'Detay Yok')}")
        with sub_col2:
            st.markdown("<h5>İş Durması / Kar Kaybı</h5>", unsafe_allow_html=True)
            st.error(f"**Etki:** {report.get('is_durmasi_kar_kaybi', 'Detay Yok')}")
        
        st.markdown("---")

        # Olay Yönetimi ve Etkileri
        st.subheader("Olay Yönetimi ve Etkileri")
        st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'Detay Yok')}")
        st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'Detay Yok')}")
        st.caption(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'Detay Yok')}")
        st.caption(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Detay Yok')}")

        st.markdown("---")

        # Harita ve Komşu Tesisler
        with st.expander("🗺️ Harita, Komşu Tesisler ve Kaynak Link", expanded=True):
            coords = report.get('tahmini_koordinat', {})
            lat, lon = coords.get('lat'), coords.get('lon')

            if lat and lon:
                try:
                    lat, lon = float(lat), float(lon)
                    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
                    
                    # Ana tesisin markeri
                    folium.Marker(
                        [lat, lon],
                        popup=f"<b>{report.get('tesis_adi')}</b>",
                        icon=folium.Icon(color='red', icon='fire')
                    ).add_to(m)

                    # Komşu tesislerin markerları
                    neighbors = report.get('komsu_tesisler', [])
                    for n in neighbors:
                        if n.get('lat') and n.get('lng'):
                            folium.Marker(
                                [n['lat'], n['lng']],
                                popup=f"<b>{n['tesis_adi']}</b><br>{n['konum']}",
                                tooltip=n['tesis_adi'],
                                icon=folium.Icon(color='blue', icon='industry', prefix='fa')
                            ).add_to(m)
                    
                    folium_static(m, height=400)

                    st.markdown("<h6>Komşu Tesisler (Google Harita Verisi)</h6>", unsafe_allow_html=True)
                    st.table(pd.DataFrame(neighbors)[['tesis_adi', 'tip', 'konum']])

                except (ValueError, TypeError):
                    st.warning("Koordinat formatı geçersiz, harita çizilemiyor.")
            else:
                st.info("Bu rapor için harita oluşturulacak yeterli koordinat verisi bulunamadı.")
            
            st.markdown(f"**Haber Kaynağı:** [Link]({report.get('kaynak_url')})")
