# ==============================================================================
#           NİHAİ KOD (v4): GELİŞMİŞ PROMPT VE "SON 10 OLAY" MANTIĞI
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE API ANAHTARI KONTROLÜ
# ------------------------------------------------------------------------------

st.set_page_config(layout="wide")
st.title("🚨 Endüstriyel Hasar Analiz Paneli")
st.markdown("---")

API_SERVICE = "Grok_XAI" 

API_CONFIGS = {
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama3-70b-8192",
    },
    "Grok_XAI": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-4-fast-reasoning", 
    }
}
SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY"

api_key = st.secrets.get(API_KEY_NAME)

# ------------------------------------------------------------------------------
# 2. API ANAHTARINI DOĞRULAMA FONKSİYONU
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def validate_api_key(key, base_url, model):
    if not key:
        return False, f"**{API_KEY_NAME}** adında bir anahtar Streamlit Secrets içinde bulunamadı.", "Lütfen Streamlit Cloud'da uygulamanızın 'Settings > Secrets' bölümüne giderek anahtarınızı ekleyin."
    try:
        client = OpenAI(api_key=key, base_url=base_url)
        client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Merhaba"}], max_tokens=10)
        return True, f"API anahtarı doğrulandı ve **{API_SERVICE} ({model})** servisine başarıyla bağlandı!", ""
    except Exception as e:
        # Hata mesajlarını daha kullanıcı dostu hale getirelim
        error_message = str(e)
        if "401" in error_message:
            return False, "API Anahtarı Geçersiz (Hata 401).", f"Streamlit Secrets'e eklediğiniz anahtar **{API_SERVICE}** servisi tarafından reddedildi."
        elif "404" in error_message and "does not exist" in error_message:
            return False, f"Model Bulunamadı (Hata 404).", f"İstenen '{model}' modeli mevcut değil veya hesabınızın bu modele erişim izni yok."
        else:
            return False, "Bilinmeyen bir API hatası oluştu.", f"Hata detayı: {error_message}"

# ------------------------------------------------------------------------------
# 3. UYGULAMA AKIŞI: ÖNCE TEST ET, SONRA ÇALIŞTIR
# ------------------------------------------------------------------------------

st.subheader("⚙️ API Bağlantı Durumu")
is_valid, status_message, solution_message = validate_api_key(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

if is_valid:
    st.success(f"✅ **BAŞARILI:** {status_message}")
else:
    st.error(f"❌ **HATA:** {status_message}")
    st.warning(f"👉 **ÇÖZÜM ÖNERİSİ:** {solution_message}")
    st.stop()

# --- Buradan Sonrası Sadece API Testi Başarılı Olduğunda Çalışır ---
st.markdown("---")
st.header("En Son Endüstriyel Hasarlar Raporu")

@st.cache_data(ttl=3600) # Verileri saatte bir yenile
def get_industrial_events(key, base_url, model):
    client = OpenAI(api_key=key, base_url=base_url)
    
    # !!! YENİ VE GELİŞTİRİLMİŞ PROMPT !!!
    # Modelin X (Twitter) entegrasyonunu ve gerçek zamanlı arama yeteneğini kullanmasını sağlıyoruz.
    # "Son 30 gün" kısıtlamasını kaldırıp "en son 10 olay" mantığına geçiyoruz.
    prompt = f"""
    Sen, Türkiye'deki endüstriyel riskleri anlık olarak takip eden ve X (Twitter) entegrasyonunu aktif olarak kullanan bir hasar tespit uzmanısın.
    Görevin, Türkiye'de meydana gelmiş **en son 10 önemli** endüstriyel olayı (yangın, patlama, kimyasal sızıntı vb.) bulmaktır. Tarih aralığı önemli değil, en güncelden geriye doğru git.
    Bu tespiti yaparken, özellikle son dakika haber ajansları (AA, DHA), güvenilir gazetecilerin ve resmi kurumların (valilik, itfaiye) X (Twitter) hesaplarındaki paylaşımları ve teyitli web haberlerini öncelikli olarak kullan.
    Sadece sigortacılık açısından anlamlı (büyük maddi hasar, üretim durması, can kaybı) olayları dikkate al.
    Bulgularını, bir JSON dizisi (array) olarak döndür. SADECE HAM JSON DİZİSİNİ ÇIKTI VER, başka hiçbir metin ekleme.
    JSON Nesne Yapısı: ["olay_tarihi", "olay_tipi", "tesis_adi_turu", "adres_detay", "sehir", "ilce", "latitude", "longitude", "hasar_etkisi", "dogruluk_orani", "kaynaklar", "komsu_tesisler_risk_analizi"].
    Eğer olay bulamazsan, boş bir JSON dizisi döndür: [].
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            df = pd.DataFrame(json.loads(match.group(0)))
            if not df.empty:
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'])
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
                # En güncel olayların üstte olması için sıralama
                df = df.sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Veri çekme sırasında hata oluştu: {e}")
        return pd.DataFrame()

if st.button("Son 10 Olayı Analiz Et", type="primary"):
    with st.spinner("Yapay zeka ile X (Twitter) ve web kaynakları taranıyor... Bu işlem 1-2 dakika sürebilir."):
        events_df = get_industrial_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not events_df.empty:
        st.success(f"{len(events_df)} adet önemli olay tespit edildi.")
        st.subheader("Tespit Edilen Son Olaylar Listesi")
        st.dataframe(events_df)
        st.subheader("Olayların Harita Üzerinde Gösterimi")
        map_df = events_df.dropna(subset=['latitude', 'longitude'])
        if not map_df.empty:
            map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
            m = folium.Map(location=map_center, zoom_start=6)
            for _, row in map_df.iterrows():
                popup_html = f"<b>Tesis:</b> {row['tesis_adi_turu']}<br><b>Tarih:</b> {row['olay_tarihi'].strftime('%Y-%m-%d')}<br><b>Etki:</b> {str(row['hasar_etkisi'])[:200]}..."
                folium.Marker([row['latitude'], row['longitude']], popup=folium.Popup(popup_html, max_width=350), tooltip=row['tesis_adi_turu']).add_to(m)
            folium_static(m, width=1100, height=600)
        else:
            st.warning("Harita üzerinde gösterilecek geçerli konum verisi bulunamadı.")
    else:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")

st.caption("Bu analiz, yapay zeka tarafından kamuya açık veriler ve X (Twitter) paylaşımları işlenerek oluşturulmuştur.")
