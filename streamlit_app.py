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

st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analiz Paneli")
st.title("🚨 Endüstriyel Hasar Analiz Paneli")
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
# 2. API ANAHTARINI DOĞRULAMA FONKSİYONU
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def validate_api_key(key, base_url, model):
    if not key:
        return False, f"**{API_KEY_NAME}** adında bir anahtar Streamlit Secrets içinde bulunamadı.", "Lütfen Streamlit Cloud'da uygulamanızın 'Settings > Secrets' bölümüne giderek anahtarınızı ekleyin."
    try:
        client = OpenAI(api_key=key, base_url=base_url)
        # Daha hafif bir test sorgusu
        client.chat.completions.create(
            model=model, 
            messages=[{"role": "user", "content": "Test"}], 
            max_tokens=5
        )
        return True, f"API anahtarı doğrulandı ve **{API_SERVICE} ({model})** servisine başarıyla bağlandı!", ""
    except Exception as e:
        error_message = str(e)
        if "401" in error_message:
            return False, "API Anahtarı Geçersiz (Hata 401).", f"Streamlit Secrets'e eklediğiniz anahtar **{API_SERVICE}** servisi tarafından reddedildi."
        elif "404" in error_message:
            return False, f"Model Bulunamadı (Hata 404).", f"İstenen '{model}' modeli mevcut değil veya hesabınızın bu modele erişim izni yok."
        else:
            return False, f"API bağlantı hatası: {error_message}", f"Lütfen anahtarınızı ve internet bağlantınızı kontrol edin."

# ------------------------------------------------------------------------------
# 3. GELİŞMİŞ ENDÜSTRİYEL OLAY SORGULAMA FONKSİYONU (GROK PROMPT ENTEGRE)
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Verileri saatte bir yenile
def get_industrial_events(key, base_url, model):
    client = OpenAI(api_key=key, base_url=base_url)
    
    # GROK'UN ÖNERDİĞİ GELİŞMİŞ PROMPT + JSON ÇIKTI FORMATI
    prompt = """
    Sen bir sigorta uzmanısın. Görevin, Türkiye'de meydana gelmiş EN SON 10 ÖNEMLİ endüstriyel olayı (yangın, patlama, kimyasal sızıntı vb.) bulmak ve raporlamaktır.
    
    KRİTİK TALİMATLAR:
    1. Tesis adlarını web haberleri, X (Twitter) aramaları gibi kaynaklardan YÜKSEK DOĞRULUKLA TEYİT ET. Teyit edilemezse 'Teyit Edilemedi' diye belirt.
    2. Sadece sigortacılık açısından anlamlı (büyük maddi hasar, üretim durması, can kaybı) olayları seç.
    3. Son dakika haberlerini ve sosyal medya paylaşımlarını önceliklendir.
    4. Bulgularını, aşağıdaki yapıda BİR JSON DİZİSİ (array) olarak döndür. SADECE HAM JSON DİZİSİNİ ÇIKTI VER, başka hiçbir metin ekleme.
    
    JSON Nesne Yapısı: 
    [
      {
        "olay_tarihi": "YYYY-MM-DD",
        "olay_tipi": "yangın/patlama/sızıntı vb.",
        "tesis_adi_turu": "Teyit edilmiş tesis adı veya 'Teyit Edilemedi'",
        "adres_detay": "Adres bilgisi",
        "sehir": "Şehir adı",
        "ilce": "İlçe adı (biliniyorsa)",
        "latitude": 40.1234,
        "longitude": 29.1234,
        "hasar_etkisi": "Hasarın sigortacılık açısından etkisi",
        "dogruluk_orani": "Yüksek/Orta/Düşük",
        "kaynaklar": "Haber linkleri veya kaynaklar",
        "komsu_tesisler_risk_analizi": "Çevre risk analizi"
      }
    ]
    Eğer olay bulamazsan, boş bir JSON dizisi döndür: [].
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,  # JSON çıktı uzun olabileceği için arttırıldı
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        
        # JSON'u içerikten çekmek için regex
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            json_data = json.loads(match.group(0))
            df = pd.DataFrame(json_data)
            
            if not df.empty:
                # Veri tiplerini düzelt
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'], errors='coerce')
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
                
                # Boş koordinatları filtrele ve en güncel olaylar üstte olacak şekilde sırala
                df = df.dropna(subset=['olay_tarihi']).sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)
            
            return df
        
        return pd.DataFrame()
        
    except json.JSONDecodeError as e:
        st.error(f"API'den dönen yanıt JSON formatında ayrıştırılamadı: {e}")
        st.code(content)  # Hata ayıklama için ham içeriği göster
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Veri çekme sırasında beklenmeyen bir hata oluştu: {e}")
        return pd.DataFrame()

# ------------------------------------------------------------------------------
# 4. UYGULAMA AKIŞI: ÖNCE TEST ET, SONRA ÇALIŞTIR
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

# Kullanıcı arayüzü için biraz daha bilgilendirici açıklama
st.info("""
**ℹ️ Bilgi:** Bu sistem, Grok AI'nin X (Twitter) entegrasyonu ve gerçek zamanlı web tarama yeteneklerini kullanarak 
Türkiye'deki en son ve en önemli 10 endüstriyel hasarı tespit etmeye çalışır. 
Tesis isimleri özellikle yüksek doğrulukla teyit edilmeye çalışılır.
""")

if st.button("🔍 Son 10 Kritik Olayı Araştır", type="primary", help="Grok API'sini kullanarak en son endüstriyel olayları tarar"):
    with st.spinner("Yapay zeka ile X (Twitter) ve web kaynakları taranıyor... Bu işlem 1-2 dakika sürebilir."):
        events_df = get_industrial_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not events_df.empty:
        st.success(f"✅ {len(events_df)} adet önemli olay tespit edildi ve analiz edildi.")
        
        # Verileri Göster
        st.subheader("📋 Tespit Edilen Son Olaylar Listesi")
        
        # Daha okunabilir bir tablo için tarihi formatla
        display_df = events_df.copy()
        display_df['olay_tarihi'] = display_df['olay_tarihi'].dt.strftime('%d.%m.%Y')
        
        st.dataframe(
            display_df,
            use_container_width=True,
            column_config={
                "tesis_adi_turu": "Tesis Adı",
                "olay_tipi": "Olay Tipi",
                "sehir": "Şehir",
                "hasar_etkisi": st.column_config.TextColumn("Hasar Etkisi", width="medium"),
                "dogruluk_orani": "Doğruluk",
                "kaynaklar": st.column_config.LinkColumn("Kaynaklar", display_text="Link")
            }
        )
        
        # Harita Gösterimi
        st.subheader("🗺️ Olayların Harita Üzerinde Gösterimi")
        map_df = events_df.dropna(subset=['latitude', 'longitude'])
        
        if not map_df.empty:
            # Harita merkezini Türkiye'ye sabitle
            map_center = [39.5, 35.5]  # Türkiye merkez koordinatları
            m = folium.Map(location=map_center, zoom_start=6)
            
            for _, row in map_df.iterrows():
                # Detaylı popup içeriği
                popup_html = f"""
                <div style="width: 250px;">
                    <h4>{row['tesis_adi_turu']}</h4>
                    <p><b>Tarih:</b> {row['olay_tarihi'].strftime('%d.%m.%Y')}<br>
                    <b>Tip:</b> {row['olay_tipi']}<br>
                    <b>Şehir:</b> {row['sehir']}<br>
                    <b>Doğruluk:</b> {row['dogruluk_orani']}</p>
                    <p><b>Etki:</b> {str(row['hasar_etkisi'])[:150]}...</p>
                </div>
                """
                folium.Marker(
                    [row['latitude'], row['longitude']],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=row['tesis_adi_turu'],
                    icon=folium.Icon(color='red', icon='fire', prefix='fa')
                ).add_to(m)
            
            folium_static(m, width=1100, height=600)
        else:
            st.warning("Harita üzerinde gösterilecek geçerli konum verisi bulunamadı.")
            
        # Ham Veriyi İnceleme Seçeneği (Geliştirici için)
        with st.expander("📊 Ham Veriyi İncele (Geliştirici)"):
            st.json(events_df.to_dict(orient='records'))
            
    else:
        st.info("""
        🤷‍♂️ Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi. 
        Bu, gerçekten olay olmamasından veya API'nin sınırlamalarından kaynaklanıyor olabilir.
        """)

# Footer
st.markdown("---")
st.caption("""
⚠️ Bu analiz, yapay zeka tarafından kamuya açık veriler ve X (Twitter) paylaşımları işlenerek oluşturulmuştur. 
Doğruluk garantisi yoktur, profesyonel sigorta incelemesi yerine geçmez.
""")
