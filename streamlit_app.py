# ==============================================================================
#      NİHAİ KOD (v18.0): Sıfırlanmış, Odaklanmış ve Stabil Analiz Motoru
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE BAĞLANTILAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analizi")
st.title("🛰️ Akıllı Endüstriyel Hasar Analiz Motoru (Test Modu)")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=600) # 10 dakikalık cache
def get_single_latest_event(_client):
    prompt = f"""
    Sen, Türkiye odaklı çalışan, elit seviye bir sigorta ve risk istihbarat analistisin. Görevinin merkezinde doğruluk, kanıt ve derinlemesine detay vardır. Yüzeysel özetler kabul edilemez.

    ANA GÖREVİN: Web'i (haber ajansları) ve X'i (Twitter) aktif olarak tarayarak Türkiye'de son 10 gün içinde meydana gelmiş, sigortacılık açısından **en önemli ve en güncel TEK BİR** endüstriyel veya enerji tesisi hasar olayını bul.

    KRİTİK TALİMATLAR:
    1.  **DERİNLEMESİNE BİLGİ TOPLA:** Sadece başlıkları değil, bulduğun haber metinlerinin ve X paylaşımlarının içeriğini OKU.
    2.  **KAYNAK GÖSTERME ZORUNLUDUR:** Özellikle tesis adı ve hasar tahmini gibi kritik bilgiler için kaynağını belirt. (Örn: "Tesis Adı: ABC Kimya A.Ş. (Kaynak: X kullanıcısı @... ve DHA haberi)").

    ÇIKTI FORMATI: Bulgularını, aşağıdaki detaylı anahtarlara sahip TEK BİR JSON nesnesi olarak döndür. Dizi ([]) içinde değil, doğrudan nesne ({}) olarak.
    
    JSON NESNE YAPISI:
    - "event_key": Olayı benzersiz kılan bir anahtar kelime (Örn: "Gebze_Kimya_Yangini_2025_09_20").
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kaynak": Tesis adını hangi kaynaklara dayanarak bulduğunun açıklaması.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG formatında).
    - "hasarin_nedeni": Olayın tahmini nedeni (Örn: "Elektrik panosundaki kısa devre").
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (Örn: "Fabrikanın 5000 metrekarelik depo bölümü tamamen yandı.").
    - "yapilan_mudahale": Resmi kurumların müdahalesi (Örn: "Olay yerine 15 itfaiye aracı sevk edildi.").
    - "hasar_tahmini_parasal": Parasal hasar bilgisi ve kaynağı (Örn: "İlk belirlemelere göre 25 Milyon TL. Kaynak: Şirket sahibinin açıklaması.").
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "komsu_tesisler_metin": Haber metinlerinde, olayın komşu tesislere olan etkisinden bahsediliyor mu?
    - "latitude": Olay yerinin enlemi (Sadece sayı, tahmin de olabilir).
    - "longitude": Olay yerinin boylamı (Sadece sayı, tahmin de olabilir).
    - "analiz_guveni": Bu rapordaki bilgilerin genel güvenilirliğine 1-5 arası verdiğin puan.
    - "analiz_sureci_ozeti": Bu raporu hazırlarken hangi adımları attığının kısa özeti.
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi (dizi).
    """
    try:
        response = client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return None

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
run_analysis = st.sidebar.button("En Son Önemli Olayı Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("Web'i ve X'i tarayarak en güncel ve önemli tek bir olayı bulur, detaylı analiz eder.")

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.spinner("Ana Analiz Motoru çalıştırılıyor... Bu işlem birkaç dakika sürebilir."):
        report = get_single_latest_event(client)

    if not report:
        st.error("Analiz motoru bir olay raporu üretemedi veya uygun bir olay bulamadı.")
    else:
        st.success("Analiz başarıyla tamamlandı!")
        
        with st.spinner("Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor..."):
            report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
        
        st.markdown("---")
        st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        
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

            st.markdown("##### Komşu Tesis Analizi (Haber Metinlerinden)")
            st.write(report.get('komsu_tesisler_metin', 'Metinlerde komşu tesislere dair bir bilgi bulunamadı.'))
            
            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
