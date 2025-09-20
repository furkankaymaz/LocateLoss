# ==============================================================================
#           NİHAİ KOD: KENDİ KENDİNİ TEST EDEN STREAMLIT UYGULAMASI
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

# HANGİ API'Yİ KULLANIYORSUNUZ? (Bu ayar önemli)
# Eğer anahtarınız groq.com'dan ise: "Groq"
# Eğer anahtarınız x.ai'dan (Elon Musk'ın Grok'u) ise: "Grok_XAI"
API_SERVICE = "Groq" 

# API ayarları
API_CONFIGS = {
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama3-70b-8192",
        "key_prefix": "gsk_"
    },
    "Grok_XAI": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-1", # Bu model adı değişebilir, x.ai dokümanlarına bakın
        "key_prefix": "" # x.ai anahtarının ön eki farklı olabilir
    }
}

SELECTED_CONFIG = API_CONFIGS[API_SERVICE]
API_KEY_NAME = "GROK_API_KEY" # Streamlit Secrets'teki anahtar adı

# Secrets'ten API anahtarını güvenli bir şekilde çekelim
api_key = None
try:
    api_key = st.secrets.get(API_KEY_NAME)
except Exception:
    pass # Hata durumunda api_key None olarak kalacak

# ------------------------------------------------------------------------------
# 2. API ANAHTARINI DOĞRULAMA FONKSİYONU
#    Bu fonksiyon, anahtarın geçerli olup olmadığını test eder.
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Testi 1 saatte bir yap, sürekli API'yi yorma
def validate_api_key(key, base_url, model):
    if not key:
        return False, f"**{API_KEY_NAME}** adında bir anahtar Streamlit Secrets içinde bulunamadı.", "Streamlit Cloud > uygulamanız > Settings > Secrets bölümüne giderek anahtarınızı ekleyin."

    if not isinstance(key, str) or len(key) < 10:
         return False, "API anahtarı geçersiz formatta.", f"Streamlit Secrets'e eklediğiniz **{API_KEY_NAME}** değerini kontrol edin. Çok kısa veya hatalı görünüyor."

    try:
        client = OpenAI(api_key=key, base_url=base_url)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Merhaba de"}],
            max_tokens=10
        )
        return True, "API anahtarı doğrulandı ve başarıyla bağlandı!", ""
    except Exception as e:
        error_message = str(e)
        if "401" in error_message:
            return False, f"API Anahtarı Geçersiz (Hata 401). Sunucu bu anahtarı reddetti.", f"**Çözüm:** Kullandığınız **{API_SERVICE}** servisine ait API anahtarının doğru olduğundan emin olun. Gerekirse servisin web sitesinden **yeni bir anahtar oluşturup** Streamlit Secrets'e ekleyin."
        elif "connection error" in error_message.lower():
            return False, "Bağlantı Hatası.", f"API sunucusuna ({base_url}) ulaşılamıyor. Sunucu geçici olarak kapalı olabilir veya bir sorun yaşıyor olabilir."
        else:
            return False, f"Bilinmeyen bir API hatası oluştu.", f"Hata detayı: {error_message}"

# ------------------------------------------------------------------------------
# 3. UYGULAMA AKIŞI: ÖNCE TEST ET, SONRA ÇALIŞTIR
# ------------------------------------------------------------------------------

# API anahtarını doğrula ve sonucu ekranda göster
st.subheader("⚙️ API Bağlantı Testi")
is_valid, status_message, solution_message = validate_api_key(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

if is_valid:
    st.success(f"✅ **BAŞARILI:** {status_message}")
else:
    st.error(f"❌ **HATA:** {status_message}")
    st.warning(f"👉 **ÇÖZÜM ÖNERİSİ:** {solution_message}")
    st.stop() # Hata varsa uygulamayı burada durdur, devam etme

# --- BURADAN SONRASI SADECE API TESTİ BAŞARILI OLURSA GÖRÜNÜR ---

st.markdown("---")
st.header("Son 30 Günlük Endüstriyel Hasar Raporu")

@st.cache_data(ttl=86400) # Verileri günde bir kez çek
def get_industrial_events(key, base_url, model):
    client = OpenAI(api_key=key, base_url=base_url)
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    prompt = f"""
    Sen, Türkiye'deki endüstriyel riskleri analiz eden uzman bir sigorta hasar eksperisin. Görevin, son 30 gün içinde ({start_date} - {end_date}) Türkiye'de meydana gelen önemli endüstriyel olayları (yangın, patlama, kimyasal sızıntı, sel, deprem kaynaklı hasar vb.) tespit etmektir. Sadece teyit edilmiş ve sigortacılık açısından anlamlı (büyük maddi hasar, üretim durması, can kaybı) olayları dikkate al. Bulgularını, bir JSON dizisi (array) olarak döndür. YALNIZCA HAM JSON DİZİSİNİ ÇIKTI VER, başka hiçbir metin ekleme. JSON Nesne Yapısı: ["olay_tarihi", "olay_tipi", "tesis_adi_turu", "adres_detay", "sehir", "ilce", "latitude", "longitude", "hasar_etkisi", "dogruluk_orani", "kaynaklar", "komsu_tesisler_risk_analizi"]. Eğer olay bulamazsan, boş bir JSON dizisi döndür: [].
    """
    
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            df = pd.DataFrame(json.loads(match.group(0)))
            if not df.empty:
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'])
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Veri çekme sırasında hata oluştu: {e}")
        return pd.DataFrame()

if st.button("Analizi Başlat (Son 30 Gün)", type="primary"):
    with st.spinner("Yapay zeka ile risk analizi yapılıyor, veriler taranıyor..."):
        events_df = get_industrial_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not events_df.empty:
        st.success(f"{len(events_df)} adet önemli olay tespit edildi.")
        # ... (Geri kalan veri gösterme ve harita kodları buraya eklenebilir)
        st.dataframe(events_df)
    else:
        st.info("Son 30 gün içinde belirtilen kriterlere uygun, raporlanacak büyük bir endüstriyel olay tespit edilemedi.")
