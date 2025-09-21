# ==============================================================================
#  "Sıfır Noktası" MVP (v40.0): En Basit ve Direkt Analiz
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Direkt AI Hasar Tespiti")
st.title("🛰️ Direkt AI Hasar Tespit Motoru")
st.info("Bu motor, yapay zekanın kendi dahili bilgi birikimini ve arama yeteneklerini kullanarak en güncel olayları bulur.")

# --- API Bağlantısı ---
grok_api_key = st.secrets.get("GROK_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYON: TEK ADIMDA TESPİT VE RAPORLAMA
# ------------------------------------------------------------------------------

@st.cache_data(ttl=1800) # Sonuçları 30 dakika önbellekte tut
def get_events_directly_from_ai(_client):
    """
    Tek bir AI çağrısı ile en son olayları bulur, analiz eder ve yapılandırılmış
    bir formatta döndürür. Web scraping veya RSS yoktur.
    """
    prompt = f"""
    Sen, Türkiye'deki endüstriyel riskleri anlık olarak takip eden, en güncel bilgilere erişimi olan ve X (Twitter) dahil olmak üzere kamuya açık web kaynaklarını tarayabilen elit bir istihbarat analistisin.

    ANA GÖREVİN: Türkiye'de son 15 gün içinde meydana gelmiş, sigortacılık açısından en önemli **en fazla 5 adet** endüstriyel veya enerji tesisi hasar olayını (yangın, patlama, büyük kaza vb.) bul ve her biri için detaylı bir rapor oluştur.

    KRİTİK TALİMATLAR:
    1.  **TESİS ADINI BULMAYA ODAKLAN:** Her olay için, olayın yaşandığı tesisin ticari unvanını tespit etmeye çalış. Bu bilgiyi hangi kaynağa (örn: AA haberi, Valilik açıklaması) dayandırdığını "tesis_adi_kanit" alanında belirt.
    2.  **KANITA DAYALI OL:** Bilgileri doğrulanabilir kaynaklara dayandır. Eğer bir bilgi (örn: hasar miktarı) spekülatif ise, bunu belirt. ASLA bilgi uydurma.
    3.  **SADECE JSON ÇIKTISI VER:** Bulgularını, aşağıda belirtilen yapıya sahip bir JSON dizisi (array) olarak döndür. Başka hiçbir metin veya açıklama ekleme. Eğer uygun bir olay bulamazsan, boş bir JSON dizisi `[]` döndür.

    JSON NESNE YAPISI (Her bir olay için):
    {{
      "tesis_adi": "Yüksek doğrulukla tespit edilmiş ticari unvan.",
      "tesis_adi_kanit": "Bu ismin tespit edildiği kaynak veya yöntem.",
      "sehir_ilce": "Olayın yaşandığı yer.",
      "olay_tarihi": "YYYY-AA-GG formatında olay tarihi.",
      "olay_ozeti": "Hasarın fiziksel boyutu, nedeni ve etkilerini içeren kısa özet.",
      "guncel_durum": "Üretim durdu mu, soğutma çalışmaları sürüyor mu gibi en son bilgiler.",
      "kaynak_url": "Bulduğun en güvenilir haberin veya resmi açıklamanın linki.",
      "latitude": "Olay yerinin enlemi (Sadece sayı).",
      "longitude": "Olay yerinin boylamı (Sadece sayı)."
    }}
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            df = pd.DataFrame(json.loads(match.group(0)))
            # Veri tiplerini dönüştürme ve sıralama
            if not df.empty:
                df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'], errors='coerce')
                df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
                df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
                df = df.sort_values(by='olay_tarihi', ascending=False).reset_index(drop=True)
            return df
        return pd.DataFrame() # Eşleşme yoksa boş DataFrame döndür
    except Exception as e:
        st.error(f"AI Analizi sırasında hata oluştu: {e}")
        return pd.DataFrame()

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

if st.sidebar.button("🤖 En Son Olayları Analiz Et", type="primary", use_container_width=True):
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.spinner("AI, dahili bilgi bankasını ve web kaynaklarını tarıyor... Bu işlem 1-2 dakika sürebilir."):
        events_df = get_events_directly_from_ai(client)

    if not events_df.empty:
        st.success(f"AI, analiz edilecek {len(events_df)} adet önemli olay tespit etti.")
        st.session_state.events_df = events_df
    else:
        st.warning("AI, belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edemedi.")
        st.session_state.events_df = pd.DataFrame()

if 'events_df' in st.session_state and not st.session_state.events_df.empty:
    events_df = st.session_state.events_df
    
    st.header("Tespit Edilen Olaylar")
    for index, row in events_df.iterrows():
        with st.expander(f"**{row['olay_tarihi'].strftime('%d %b %Y')} - {row['tesis_adi']}** ({row['sehir_ilce']})", expanded=index==0):
            st.markdown(f"**Özet:** {row['olay_ozeti']}")
            st.info(f"**Güncel Durum:** {row['guncel_durum']}")
            st.caption(f"**Tesis Adı Kanıtı:** {row['tesis_adi_kanit']}")
            st.caption(f"**Kaynak:** [{row['kaynak_url']}]({row['kaynak_url']})")

    st.header("Olayların Harita Üzerinde Gösterimi")
    map_df = events_df.dropna(subset=['latitude', 'longitude'])
    if not map_df.empty:
        map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
        m = folium.Map(location=map_center, zoom_start=6, tiles="CartoDB positron")
        for _, row in map_df.iterrows():
            popup_html = f"<b>{row['tesis_adi']}</b><br>{row['sehir_ilce']}<br><i>{row['olay_ozeti'][:100]}...</i>"
            folium.Marker(
                [row['latitude'], row['longitude']], 
                popup=folium.Popup(popup_html, max_width=300), 
                tooltip=row['tesis_adi'],
                icon=folium.Icon(color='red', icon='fire')
            ).add_to(m)
        folium_static(m, height=500)
    else:
        st.warning("Harita üzerinde gösterilecek geçerli konum verisi bulunamadı.")
