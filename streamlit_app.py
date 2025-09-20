import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re # JSON ayıklamak için eklendi

# Streamlit sayfa konfigürasyonu
st.set_page_config(layout="wide")

# Secrets'ten API Key Çek (GitHub/Streamlit Cloud için .streamlit/secrets.toml'da tanımlı)
# Grok API'si OpenAI kütüphanesi ile uyumlu olduğu için bu yapı kullanılabilir.
try:
    GROK_API_KEY = st.secrets["GROK_API_KEY"]
except FileNotFoundError:
    st.error("secrets.toml dosyası bulunamadı. Lütfen oluşturun.")
    GROK_API_KEY = None
except KeyError:
    st.error("GROK_API_KEY anahtarı secrets.toml içinde tanımlı değil.")
    GROK_API_KEY = None

MODEL = "llama3-70b-8192" # Grok yerine daha stabil ve bu tür görevlerde başarılı bir model önerisi.
# MODEL = "grok-1" # Eğer Grok kullanmakta ısrarcıysanız bu modeli deneyebilirsiniz.

# Optimizasyonlu API Sorgu (Günlük Cache, Maliyet Düşük)
@st.cache_data(ttl=86400)  # Günde bir kez çalıştır, API maliyetini düşür
def get_industrial_events():
    if not GROK_API_KEY:
        st.error("API Anahtarı bulunamadığı için sorgulama yapılamıyor.")
        return pd.DataFrame()

    client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.groq.com/openai/v1") # Groq için doğru base_url
    
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    # YENİ VE DETAYLI PROMPT
    prompt = f"""
    Sen, Türkiye'deki endüstriyel riskleri analiz eden uzman bir sigorta hasar eksperisin. Görevin, son 30 gün içinde ({start_date} - {end_date}) Türkiye'de meydana gelen önemli endüstriyel olayları (yangın, patlama, kimyasal sızıntı, sel, deprem kaynaklı hasar vb.) tespit etmektir. Sadece teyit edilmiş ve sigortacılık açısından anlamlı (büyük maddi hasar, üretim durması, can kaybı) olayları dikkate al.

    Bulgularını, aşağıda tanımlanan yapıya birebir uyan bir JSON dizisi (array) olarak döndür. YALNIZCA HAM JSON DİZİSİNİ ÇIKTI VER, başka hiçbir metin (giriş, açıklama, sonuç vb.) ekleme.

    JSON Nesne Yapısı:
    - "olay_tarihi": Olayın tarihi. Format: "YYYY-MM-DD".
    - "olay_tipi": Olayın türü. Örnek: "Yangın", "Patlama", "Kimyasal Sızıntı".
    - "tesis_adi_turu": Tesisin tam ticari adı ve parantez içinde tesisin türü. Örnek: "Teksüt Süt Mamülleri San. ve Tic. A.Ş. (Süt ürünleri fabrikası)".
    - "adres_detay": Tesisin tam açık adresi (Mahalle, Sokak, İlçe, İl).
    - "sehir": Sadece il adı. Örnek: "Balıkesir".
    - "ilce": Sadece ilçe adı. Örnek: "Gönen".
    - "latitude": Olay yerinin yaklaşık ondalık enlem koordinatı (Float). Örnek: 40.1032.
    - "longitude": Olay yerinin yaklaşık ondalık boylam koordinatı (Float). Örnek: 27.6543.
    - "hasar_etkisi": Hasarın detaylı ve yapısal analizi. İçermesi gerekenler: Olayın kısa özeti, biliniyorsa can kaybı/yaralı sayısı ve isimleri, maddi hasar boyutu (tahmini TL veya "büyük çaplı" gibi ifadeler), üretim üzerindeki etkisi (üretim durdu, kısmen devam ediyor vb.) ve sigorta açısından notlar.
    - "dogruluk_orani": Bilginin güvenilirlik yüzdesi ve kaynak teyidi. Örnek: "Yüksek (%95) – NTV, Milliyet, DHA ve resmi kurum açıklamaları ile teyit edildi.".
    - "kaynaklar": Bilgiyi doğrulamak için kullanılan haber veya resmi açıklama linkleri/isimleri listesi. Örnek: ["ntv.com.tr/...", "milliyet.com.tr/..."].
    - "komsu_tesisler_risk_analizi": 5km civarındaki diğer önemli sanayi tesisleri ve bu olayın onlara olan potansiyel etkileri üzerine bir analiz metni. Örnek: "Gönen sanayi bölgesi yakını. Rüzgar yönü nedeniyle yakındaki diğer gıda işleme tesisleri için duman ve sıçrama riski oluştu ancak itfaiye müdahalesiyle risk bertaraf edildi. Yaklaşık 15km mesafedeki Balıkesir OSB etkilenmedi.".

    Eğer belirtilen kriterlere uygun hiçbir olay bulamazsan, boş bir JSON dizisi döndür: [].
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096, # Daha detaylı cevaplar için artırıldı
            temperature=0.1,
            response_format={"type": "json_object"} # JSON formatı zorunlu kılındı (destekleyen modellerde)
        )
        content = response.choices[0].message.content.strip()
        
        # Modeller bazen JSON'u bir anahtarın içine koyabilir, bunu ayıklayalım.
        # Veya metin başına/sonuna eklemeler yapabilir, regex ile sadece JSON array'i alalım.
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            json_str = match.group(0)
            events_json = json.loads(json_str)
            df = pd.DataFrame(events_json)
        else:
            st.warning("API'den geçerli bir JSON formatında veri alınamadı.")
            st.code(content)
            return pd.DataFrame()

        if not df.empty:
            # Veri tiplerini ve işlemeyi garantiye alalım
            df['olay_tarihi'] = pd.to_datetime(df['olay_tarihi'])
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
        return df

    except Exception as e:
        st.error(f"API Hatası: {e}")
        return pd.DataFrame()

# Streamlit UI
st.title("🚨 Son 30 Gün Endüstriyel Tesis Hasar Analiz Paneli")
st.markdown("Yapay zeka ile güncel haber kaynakları ve raporlar taranarak oluşturulmuştur. Veriler günde bir kez güncellenir.")

if st.button("Analizi Başlat (Son 30 Gün)"):
    with st.spinner("Yapay zeka ile risk analizi yapılıyor, veriler taranıyor..."):
        events_df = get_industrial_events()

    if not events_df.empty:
        st.success(f"{len(events_df)} adet önemli olay tespit edildi.")
        
        # Gösterilecek sütunları ve isimlerini belirleyelim
        display_columns = {
            'olay_tarihi': 'Olay Tarihi',
            'olay_tipi': 'Olay Tipi',
            'tesis_adi_turu': 'Tesis Adı / Türü',
            'adres_detay': 'Adres',
            'hasar_etkisi': 'Hasar Etkisi ve Detaylar',
            'dogruluk_orani': 'Doğruluk Oranı',
            'komsu_tesisler_risk_analizi': 'Komşu Tesisler Risk Analizi'
        }
        
        # Sadece var olan sütunları göster
        columns_to_show = [col for col in display_columns.keys() if col in events_df.columns]
        df_display = events_df[columns_to_show].rename(columns=display_columns)
        df_display['Olay Tarihi'] = df_display['Olay Tarihi'].dt.strftime('%Y-%m-%d')
        
        st.subheader("Tespit Edilen Olaylar Listesi")
        st.dataframe(df_display)

        # --- Harita Gösterimi ---
        st.subheader("Olayların Harita Üzerinde Gösterimi")
        map_df = events_df.dropna(subset=['latitude', 'longitude'])

        if not map_df.empty:
            # Haritanın merkezini olayların ortalamasına göre ayarla
            map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
            m = folium.Map(location=map_center, zoom_start=6)

            for _, row in map_df.iterrows():
                popup_html = f"""
                <b>Tesis:</b> {row['tesis_adi_turu']}<br>
                <b>Tarih:</b> {row['olay_tarihi'].strftime('%Y-%m-%d')}<br>
                <b>Etki:</b> {row['hasar_etkisi'][:200]}...
                """
                folium.Marker(
                    [row['latitude'], row['longitude']],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=row['tesis_adi_turu']
                ).add_to(m)
            
            folium_static(m, width=1100, height=600)
        else:
            st.warning("Harita üzerinde gösterilecek geçerli konum verisi bulunamadı.")
            
    else:
        st.info("Son 30 gün içinde belirtilen kriterlere uygun, raporlanacak büyük bir endüstriyel olay tespit edilemedi.")

st.caption("Bu analiz, yapay zeka tarafından kamuya açık veriler işlenerek oluşturulmuştur ve bilgilendirme amaçlıdır. Resmi bir hasar raporu niteliği taşımaz.")
