# ==============================================================================
#      NİHAİ KOD (v23.0): "Şaşırtıcı Detay" Sürümü
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

@st.cache_data(ttl=600)
def get_single_latest_event(_client):
    # GÜNCELLEME: Prompt, tüm yeni ve detaylı alanları içerecek şekilde güncellendi.
    prompt = f"""
    Sen, Türkiye odaklı çalışan, kanıta dayalı ve aşırı detaycı bir sigorta istihbarat analistisin. Yüzeysel özetler KESİNLİKLE kabul edilemez.

    ANA GÖREVİN: Web'i (haber ajansları) ve X'i (Twitter) aktif olarak tarayarak Türkiye'de son 10 gün içinde meydana gelmiş, sigortacılık açısından **en önemli ve en güncel TEK BİR** endüstriyel veya enerji tesisi hasar olayını bul.

    KRİTİK TALİMATLAR:
    1.  **DERİNLEMESİNE BİLGİ TOPLA:** Sadece başlıkları değil, bulduğun haber metinlerinin ve X paylaşımlarının içeriğini OKU.
    2.  **KANIT GÖSTER:** Tesis adı için, ismin geçtiği orijinal cümleyi birebir alıntıla.
    3.  **SPESİFİK KONUM BUL:** Koordinat üretmeden önce metinlerden sokak, mahalle veya OSB gibi spesifik bir adres bulmaya çalış. Koordinatları bu spesifik adrese göre tahmin et. Sadece şehir bulabiliyorsan koordinatları null döndür.

    ÇIKTI FORMATI: Bulgularını TEK BİR JSON nesnesi olarak döndür.
    
    JSON NESNE YAPISI:
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kaynak": Tesis adını hangi kaynaklara dayandığının özeti.
    - "tesis_adi_kanit": Tesis adının geçtiği cümlenin doğrudan alıntısı.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG formatında).
    - "hasarin_nedeni": Olayın tahmini nedeni.
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (yüzölçümü, etkilenen birimler vb.).
    - "yapilan_mudahale": Resmi kurumların müdahalesi (itfaiye sayısı, süre vb.).
    - "hasar_tahmini_parasal": Parasal hasar bilgisi ve kaynağı.
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "cevreye_etki": Duman, sızıntı gibi çevreye olan etkilerin özeti.
    - "latitude": Olay yerinin spesifik enlemi (Sadece sayı).
    - "longitude": Olay yerinin spesifik boylamı (Sadece sayı).
    - "gorsel_url": Olayla ilgili en net fotoğrafın doğrudan URL'si (.jpg, .png vb.).
    - "analiz_guveni": Bu rapordaki bilgilerin genel güvenilirliğine 1-5 arası verdiğin puan.
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi.
    """
    try:
        response = client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return None

# GÜNCELLEME: Bu fonksiyon artık komşuların koordinatlarını da döndürüyor.
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
            neighbors.append({
                "tesis_adi": p.get('name'),
                "tip": ", ".join(p.get('types', [])),
                "lat": loc.get('lat'),
                "lng": loc.get('lng')
            })
        return neighbors
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

    report = None
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1: AI Analiz Motoru çalıştırılıyor: Olay derinlemesine inceleniyor...")
        report = get_single_latest_event(client)
        
        if report:
            status.write("Aşama 2: Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor...")
            report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
            status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
        else:
            status.update(label="Analiz Başarısız Oldu!", state="error", expanded=True)

    if report:
        st.markdown("---")
        st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        
        if report.get('gorsel_url'):
            st.image(report['gorsel_url'], caption=f"Olay Yerinden Görüntü (Güven Skoru: {report.get('analiz_guveni', 'N/A')}/5)")

        st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"* - (Kaynak: {report.get('tesis_adi_kaynak', 'N/A')})")
        
        col1, col2 = st.columns(2)
        with col1:
            st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
        with col2:
            st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")

        st.metric(label="Parasal Hasar Tahmini", value=report.get('hasar_tahmini_parasal', 'Tespit Edilemedi'))
        
        st.info(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Tespit Edilemedi.')}")

        with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
            lat, lon = report.get('latitude'), report.get('longitude')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                    # Ana Tesisi Kırmızı İşaretle
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    
                    # GÜNCELLEME: Komşu tesisleri haritaya mavi ikonlarla ekle
                    neighbors = report.get('komsu_tesisler_harita', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker(
                                [neighbor['lat'], neighbor['lng']], 
                                popup=f"<b>{neighbor['tesis_adi']}</b><br><i>Tip: {neighbor['tip']}</i>", 
                                tooltip=neighbor['tesis_adi'],
                                icon=folium.Icon(color='blue', icon='industry', prefix='fa')
                            ).add_to(m)
                    
                    folium_static(m, height=500)
                except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak en son olayın analizini başlatın.")
