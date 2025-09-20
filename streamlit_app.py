# ==============================================================================
#           NİHAİ KOD (v5): GELİŞMİŞ ARAYÜZ VE DERİN ANALİZ
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------

st.set_page_config(layout="wide")
st.title("🚨 Akıllı Endüstriyel Hasar Takip Platformu")
st.markdown("---")

API_SERVICE = "Grok_XAI" 
API_CONFIGS = {
    "Grok_XAI": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-fast-reasoning", 
    }
}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY"
api_key = st.secrets.get(API_KEY_NAME)

# ------------------------------------------------------------------------------
# 2. API BAĞLANTI KONTROLÜ (Değişiklik yok)
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def validate_api_key(key, base_url, model):
    if not key: return False, "API Anahtarı bulunamadı.", "Lütfen Streamlit Secrets ayarlarınızı kontrol edin."
    try:
        OpenAI(api_key=key, base_url=base_url).chat.completions.create(model=model, messages=[{"role": "user", "content": "Test"}], max_tokens=10)
        return True, f"API bağlantısı başarılı: **{API_SERVICE} ({model})**", ""
    except Exception as e:
        return False, "API Bağlantı Hatası.", f"Detay: {e}"

st.sidebar.subheader("⚙️ API Bağlantı Durumu")
is_valid, status_message, solution_message = validate_api_key(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])
if is_valid:
    st.sidebar.success(f"✅ {status_message}")
else:
    st.sidebar.error(f"❌ {status_message}")
    st.sidebar.warning(solution_message)
    st.stop()

# ------------------------------------------------------------------------------
# 3. VERİ ÇEKME VE İŞLEME
# ------------------------------------------------------------------------------

# Optimizasyon Notu: ttl=900, API'ye yapılan çağrıları 15 dakika boyunca önbellekte tutar.
# Bu, uygulamayı her yenilediğinizde maliyetli bir API çağrısı yapılmasını engeller.
@st.cache_data(ttl=900)
def get_industrial_events(key, base_url, model):
    client = OpenAI(api_key=key, base_url=base_url)
    
    # !!! YENİ VE EN GELİŞMİŞ PROMPT (v5) !!!
    prompt = f"""
    Sen, Türkiye'deki endüstriyel riskleri anlık olarak takip eden, X (Twitter) ve güvenilir haber kaynaklarını karşılaştırmalı olarak analiz eden lider bir sigorta hasar eksperisin.
    Görevin, Türkiye'de meydana gelmiş **en son 10 önemli** endüstriyel hasar olayını bulmaktır.
    
    ANALİZ KRİTERLERİ:
    1.  **Firma Tespiti:** Olaydan etkilenen firmanın tam ve doğru **ticari unvanını** bulmaya odaklan.
    2.  **Kaynak Doğrulama:** X (Twitter), Anadolu Ajansı, DHA, İHA, yerel haber siteleri gibi en az 3 farklı kaynağı çapraz kontrol et.
    3.  **Derin Hasar Analizi:** Hasarın operasyonel (üretim durması, sevkiyat aksaması) ve finansal (tahmini zarar) etkilerini detaylandır.
    4.  **Komşu Riski:** Olayın konumuna ve niteliğine (kimyasal, yangın vb.) göre çevresindeki diğer sanayi tesisleri için oluşturduğu potansiyel riskleri analiz et.
    
    JSON ÇIKTI FORMATI:
    Bulgularını, aşağıdaki yapıya birebir uyan bir JSON dizisi olarak döndür. SADECE HAM JSON DİZİSİNİ ÇIKTI VER.
    - "olay_tarihi": "YYYY-MM-DD"
    - "tesis_adi_ticari_unvan": "Doğru ve tam ticari unvan."
    - "sehir_ilce": "İl, İlçe"
    - "olay_tipi_ozet": "Kısa olay tanımı. Örnek: 'Depo Bölümünde Çıkan Büyük Yangın'"
    - "hasar_detaylari_ve_etkisi": "Maddi hasar tahmini, can kaybı/yaralı durumu, üretimin durup durmadığı gibi tüm operasyonel ve finansal etkileri içeren detaylı paragraf."
    - "orjinal_haber_metni": "Bulduğun en açıklayıcı haber metni veya X (Twitter) gönderisi."
    - "dogruluk_skoru_ve_gerekcelendirme": "Yüzdesel bir skor ve gerekçesi. Örnek: '%95 - AA, DHA ve Valilik açıklamasıyla teyit edildi.'"
    - "komsu_tesisler_risk_analizi": "Yakın çevredeki OSB, fabrika gibi tesisler için risk analizi."
    - "kaynak_linkleri": ["https://... (tıklanabilir tam link)", "https://..."]
    - "latitude": Ondalık formatta enlem.
    - "longitude": Ondalık formatta boylam.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.2)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            df = pd.DataFrame(json.loads(match.group(0)))
            if not df.empty:
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'])
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
                df = df.sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Veri çekme sırasında hata oluştu: {e}")
        return pd.DataFrame()

# ------------------------------------------------------------------------------
# 4. GÖRSEL ARAYÜZ
# ------------------------------------------------------------------------------
st.header("📈 En Son Tespit Edilen Hasarlar")
if st.button("En Son Olayları Getir ve Analiz Et", type="primary", use_container_width=True):
    with st.spinner("Yapay zeka ile X (Twitter) ve çoklu haber kaynakları taranıyor, analiz yapılıyor..."):
        events_df = get_industrial_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not events_df.empty:
        st.success(f"**{len(events_df)} adet önemli olay bulundu ve analiz edildi.** Detaylar için kartları genişletin.")
        
        # --- YENİ KART GÖRÜNÜMÜ ---
        for index, row in events_df.iterrows():
            with st.expander(f"**{row['olay_tarihi'].strftime('%d %B %Y')} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**"):
                st.subheader(row['olay_tipi_ozet'])
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown("**Hasar Detayları ve Operasyonel Etki**")
                    st.write(row['hasar_detaylari_ve_etkisi'])
                
                with col2:
                    st.markdown("**Doğruluk Skoru**")
                    st.info(row['dogruluk_skoru_ve_gerekcelendirme'])

                st.markdown("**Bulunan İlk Haber Metni / Gönderi**")
                st.text_area("", value=row['orjinal_haber_metni'], height=150, disabled=True)

                st.markdown("**Komşu Tesisler İçin Risk Analizi**")
                st.warning(row['komsu_tesisler_risk_analizi'])
                
                st.markdown("**Tıklanabilir Kaynak Linkleri**")
                links_md = ""
                for link in row['kaynak_linkleri']:
                    # Linkin kısaltılmış halini gösterelim
                    domain = link.split('//')[-1].split('/')[0]
                    links_md += f"- [{domain}]({link})\n"
                st.markdown(links_md)

        # --- HARİTA GÖRÜNÜMÜ ---
        st.header("🗺️ Olayların Konumsal Dağılımı")
        map_df = events_df.dropna(subset=['latitude', 'longitude'])
        if not map_df.empty:
            map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
            m = folium.Map(location=map_center, zoom_start=6)
            for _, row in map_df.iterrows():
                popup_html = f"<b>{row['tesis_adi_ticari_unvan']}</b><br>{row['olay_tipi_ozet']}"
                folium.Marker(
                    [row['latitude'], row['longitude']],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=row['tesis_adi_ticari_unvan']
                ).add_to(m)
            folium_static(m)
        else:
            st.warning("Harita üzerinde gösterilecek geçerli konum verisi bulunamadı.")
    else:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")
