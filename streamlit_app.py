# ==============================================================================
#      NİHAİ KOD (v22.0): Odaklanmış Analiz ve Üstün Kullanıcı Deneyimi
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

# Adım 1: Otomatik Keşif - En son olayı bulur
@st.cache_data(ttl=600) # 10 dakikada bir yeni olayları kontrol et
def get_latest_event_candidate_from_rss():
    search_query = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması" OR "enerji santrali")'
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return None
        latest_entry = feed.entries[0]
        return {"headline": latest_entry.title, "url": latest_entry.link}
    except Exception as e:
        st.error(f"RSS haber kaynağına erişilirken hata oluştu: {e}")
        return None

# Adım 2: Derin Analiz - Tek bir olayı mükemmel analiz eder
@st.cache_data(ttl=3600)
def get_detailed_report_for_event(_client, event_candidate):
    prompt = f"""
    Sen, Türkiye odaklı çalışan, kanıta dayalı ve aşırı detaycı bir sigorta istihbarat analistisin. Yüzeysel raporlar KESİNLİKLE kabul edilemez.

    ANA GÖREVİN: Sana verilen '{event_candidate['headline']}' başlıklı olayı, şu linkteki haber metnini OKUYARAK ve X (Twitter) üzerinde ek araştırma yaparak analiz et: {event_candidate['url']}

    KRİTİK TALİMATLAR:
    1.  **OKU VE ARAŞTIR:** Verdiğim linkteki metnin tamamını oku. Ardından, metindeki kilit isimlerle (tesis adı, şehir vb.) X üzerinde arama yaparak ek detay, görgü tanığı ve görsel bul.
    2.  **VERİ AYIKLA, ÖZETLEME:** Görevin özetlemek değil, aşağıdaki JSON formatındaki spesifik bilgi parçalarını metinlerden ve X'ten çıkarmaktır.
    3.  **KAYNAK GÖSTER:** Tesis adı, hasar tahmini gibi kritik bilgileri hangi kaynağa dayanarak bulduğunu mutlaka belirt.

    ÇIKTI FORMATI: Bulgularını TEK BİR JSON nesnesi olarak döndür.
    
    JSON NESNE YAPISI:
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kaynak": Tesis adını hangi kaynaklara (Örn: "DHA haberi ve X kullanıcısı @...") dayanarak bulduğunun açıklaması.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG formatında).
    - "hasarin_nedeni": Olayın tahmini nedeni (Örn: "Elektrik panosundaki kısa devre").
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (Örn: "Fabrikanın 5000 metrekarelik depo bölümü tamamen yandı.").
    - "yapilan_mudahale": Resmi kurumların müdahalesi (Örn: "Olay yerine 15 itfaiye aracı sevk edildi.").
    - "hasar_tahmini_parasal": Parasal hasar bilgisi ve kaynağı (Örn: "İlk belirlemelere göre 25 Milyon TL. Kaynak: Şirket sahibinin açıklaması.").
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "latitude": Olay yerinin enlemi (Sadece sayı, tahmin de olabilir).
    - "longitude": Olay yerinin boylamı (Sadece sayı, tahmin de olabilir).
    - "gorsel_url": Olayla ilgili bulabildiğin en net fotoğrafın URL'si.
    - "analiz_guveni": Bu rapordaki bilgilerin genel güvenilirliğine 1-5 arası verdiğin puan.
    - "analiz_sureci_ozeti": Bu raporu hazırlarken hangi adımları attığının kısa özeti.
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi.
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return None

# Adım 3: Coğrafi Zenginleştirme
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:10]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Tek Olay Analizi")
run_analysis = st.sidebar.button("En Son Önemli Olayı Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En güncel ve önemli tek bir olayı bulur, derinlemesine analiz eder ve sunar.")

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    report = None
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1: Haber kaynakları taranıyor ve en güncel olay adayı bulunuyor...")
        event_candidate = get_latest_event_candidate_from_rss()
        
        if not event_candidate:
            status.update(label="Hata!", state="error", expanded=True)
            st.error("Uygun bir olay adayı bulunamadı.")
        else:
            status.write(f"En güncel olay bulundu: **{event_candidate['headline']}**")
            status.write("Aşama 2: AI Analiz Motoru çalıştırılıyor: Olay derinlemesine inceleniyor...")
            
            report = get_detailed_report_for_event(client, event_candidate)
            
            if report:
                status.write("Aşama 3: Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor...")
                report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
                status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
            else:
                status.update(label="Analiz Başarısız Oldu!", state="error", expanded=True)

    if report:
        st.markdown("---")
        st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        
        # Olay Görseli
        if report.get('gorsel_url'):
            st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (AI Tarafından Bulundu)")

        st.markdown(f"Güven Skoru: **{report.get('analiz_guveni', 'N/A')}/5** | *AI Süreç Özeti: {report.get('analiz_sureci_ozeti', 'N/A')}*")
        st.caption(f"Tesis Adı Kaynağı: {report.get('tesis_adi_kaynak', 'N/A')}")
        
        col1, col2, col3 = st.columns(3)
        with col1: st.info(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
        with col2: st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
        with col3: st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")

        st.warning(f"**Hasarın Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
        st.metric(label="Parasal Hasar Tahmini", value=report.get('hasar_tahmini_parasal', 'Tespit Edilemedi'))

        with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
            lat, lon = report.get('latitude'), report.get('longitude')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    folium_static(m, height=400)
                except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak en son olayın analizini başlatın.")
