# ==============================================================================
#           NİHAİ KOD (v6): İKİ AŞAMALI AKILLI ANALİZ
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
API_CONFIGS = {"Grok_XAI": {"base_url": "https://api.x.ai/v1", "model": "grok-4-fast-reasoning"}}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY"
api_key = st.secrets.get(API_KEY_NAME)

# ------------------------------------------------------------------------------
# 2. API BAĞLANTI KONTROLÜ
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
    st.sidebar.error(f"❌ {status_message}"); st.sidebar.warning(solution_message); st.stop()

# ------------------------------------------------------------------------------
# 3. YENİ İKİ AŞAMALI VERİ ÇEKME FONKSİYONLARI
# ------------------------------------------------------------------------------

# 1. Aşama: Sadece olayları ve linklerini bulur. Basit ve hızlıdır.
@st.cache_data(ttl=900) # Olay listesini 15 dakikada bir yenile
def find_latest_events(key, base_url, model, event_count=15):
    client = OpenAI(api_key=key, base_url=base_url)
    prompt = f"""
    Türkiye'de yakın zamanda yaşanmış en son {event_count} önemli endüstriyel hasar olayını (fabrika yangını, patlama, kimyasal sızıntı vb.) listele.
    Sadece teyit edilmiş haber kaynaklarını (AA, DHA, İHA, NTV, Hürriyet, Valilik açıklamaları) kullan.
    Çıktıyı, aşağıdaki anahtarları içeren bir JSON dizisi olarak ver. Başka hiçbir analiz yapma, sadece listele.
    - "headline": "Olayın kısa başlığı"
    - "url": "Habere ait tam ve tıklanabilir link"
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return []
    except Exception:
        return []

# 2. Aşama: Tek bir haberi derinlemesine analiz eder. Her link için ayrı çalışır ve sonuçları önbelleğe alır.
@st.cache_data(ttl=86400) # Bir kez analiz edilen bir haberi 1 gün boyunca tekrar analiz etme
def analyze_single_event(key, base_url, model, headline, url):
    client = OpenAI(api_key=key, base_url=base_url)
    prompt = f"""
    Sen lider bir sigorta hasar eksperisin. Sana verilen şu haberi analiz et:
    Başlık: "{headline}"
    Kaynak Link: "{url}"

    Bu habere dayanarak, aşağıdaki JSON formatında detaylı bir hasar raporu oluştur:
    - "olay_tarihi": "YYYY-MM-DD"
    - "tesis_adi_ticari_unvan": "Doğru ve tam ticari unvan."
    - "sehir_ilce": "İl, İlçe"
    - "olay_tipi_ozet": "Kısa olay tanımı. Örnek: 'Depo Bölümünde Çıkan Büyük Yangın'"
    - "hasar_detaylari_ve_etkisi": "Maddi hasar tahmini, can kaybı/yaralı, üretim etkisi gibi tüm detayları içeren paragraf."
    - "orjinal_haber_metni": "Haberin en önemli ve açıklayıcı kısmı veya tamamı."
    - "dogruluk_skoru_ve_gerekcelendirme": "Yüzdesel skor ve gerekçesi. Örnek: '%95 - AA ve DHA tarafından teyit edildi.'"
    - "komsu_tesisler_risk_analizi": "Yakın çevredeki tesisler için risk analizi."
    - "kaynak_linkleri": ["{url}"]
    - "latitude": Ondalık formatta enlem.
    - "longitude": Ondalık formatta boylam.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.2)
        content = response.choices[0].message.content.strip()
        return json.loads(content)
    except Exception:
        return None

# ------------------------------------------------------------------------------
# 4. GÖRSEL ARAYÜZ
# ------------------------------------------------------------------------------
st.header("📈 En Son Tespit Edilen Hasarlar")

if st.button("En Son 15 Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    with st.spinner("1. Aşama: En son olaylar ve haber linkleri taranıyor..."):
        latest_events = find_latest_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not latest_events:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")
    else:
        st.success(f"**{len(latest_events)} adet potansiyel olay bulundu.** Şimdi her biri detaylı olarak analiz ediliyor...")
        
        all_event_details = []
        progress_bar = st.progress(0, text="Analiz ilerlemesi...")

        for i, event in enumerate(latest_events):
            with st.spinner(f"2. Aşama: '{event['headline']}' haberi analiz ediliyor... ({i+1}/{len(latest_events)})"):
                event_details = analyze_single_event(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"], event['headline'], event['url'])
                if event_details:
                    all_event_details.append(event_details)
            progress_bar.progress((i + 1) / len(latest_events), text="Analiz ilerlemesi...")
        
        progress_bar.empty()
        
        if not all_event_details:
            st.warning("Olaylar bulundu ancak detaylı analiz sırasında bir sorun oluştu.")
        else:
            events_df = pd.DataFrame(all_event_details)
            events_df['olay_tarihi'] = pd.to_datetime(events_df['olay_tarihi'])
            events_df['latitude'] = pd.to_numeric(events_df['latitude'], errors='coerce')
            events_df['longitude'] = pd.to_numeric(events_df['longitude'], errors='coerce')
            events_df = events_df.sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)

            st.subheader("Analiz Edilen Son Olaylar")
            for index, row in events_df.iterrows():
                with st.expander(f"**{row['olay_tarihi'].strftime('%d %B %Y')} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**"):
                    st.subheader(row['olay_tipi_ozet'])
                    col1, col2 = st.columns([3, 1]); col1.markdown("**Hasar Detayları ve Etki**"); col1.write(row['hasar_detaylari_ve_etkisi']); col2.markdown("**Doğruluk Skoru**"); col2.info(row['dogruluk_skoru_ve_gerekcelendirme'])
                    st.markdown("**Bulunan Haber Metni**"); st.text_area("", value=row['orjinal_haber_metni'], height=150, disabled=True, key=f"text_{index}")
                    st.markdown("**Komşu Tesisler İçin Risk Analizi**"); st.warning(row['komsu_tesisler_risk_analizi'])
                    links_md = "".join([f"- [{link.split('//')[-1].split('/')[0]}]({link})\n" for link in row['kaynak_linkleri']])
                    st.markdown("**Tıklanabilir Kaynak Linkleri**\n" + links_md)

            st.header("🗺️ Olayların Konumsal Dağılımı")
            map_df = events_df.dropna(subset=['latitude', 'longitude'])
            if not map_df.empty:
                map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
                m = folium.Map(location=map_center, zoom_start=6)
                for _, row in map_df.iterrows():
                    folium.Marker([row['latitude'], row['longitude']], popup=f"<b>{row['tesis_adi_ticari_unvan']}</b>", tooltip=row['tesis_adi_ticari_unvan']).add_to(m)
                folium_static(m)

st.caption("Bu analiz, yapay zeka tarafından kamuya açık veriler ve X (Twitter) paylaşımları işlenerek oluşturulmuştur.")
