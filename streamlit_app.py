# ==============================================================================
#           NİHAİ KOD (v7): PROFESYONEL RİSK ANALİZ PLATFORMU
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

st.set_page_config(layout="wide", page_title="Endüstriyel Hasar Analizi")
st.title("🚨 Akıllı Endüstriyel Hasar Takip Platformu")
st.markdown(f"**Son Güncelleme:** {datetime.now().strftime('%d %B %Y, %H:%M')}")
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
# 3. İKİ AŞAMALI VERİ ÇEKME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def find_latest_events(key, base_url, model, event_count=15):
    client = OpenAI(api_key=key, base_url=base_url)
    current_date = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Bugünün tarihi {current_date}. Türkiye'de **son 3 ay içinde** yaşanmış endüstriyel hasar olaylarını (fabrika yangını, patlama, kimyasal sızıntı vb.) tara.
    Bulduğun tüm olaylar arasından, bana **en güncel {event_count} tanesini** listele. Bu listeyi oluştururken özellikle **son 72 saatteki** olaylara mutlak öncelik ver.
    Öncelikli kaynakların X (Twitter)'daki resmi hesaplar (valilik, itfaiye) ve ulusal haber ajansları (AA, DHA, İHA) olsun.
    Çıktıyı, aşağıdaki anahtarları içeren bir JSON dizisi olarak ver. Sadece listele, analiz yapma.
    - "headline": "Olayın kısa ve net başlığı"
    - "url": "Habere ait tam ve tıklanabilir birincil kaynak linki"
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception:
        return []

@st.cache_data(ttl=86400)
def analyze_single_event(key, base_url, model, headline, url):
    client = OpenAI(api_key=key, base_url=base_url)
    prompt = f"""
    Sen, X (Twitter) ve ulusal haber ajanslarını çapraz kontrol ederek analiz yapan lider bir sigorta hasar eksperisin. Sana verilen şu haberi profesyonel bir gözle analiz et:
    - Başlık: "{headline}"
    - Ana Kaynak Link: "{url}"

    Bu habere ve çapraz kontrolle bulacağın ek bilgilere dayanarak, aşağıdaki JSON formatında detaylı bir hasar raporu oluştur:
    - "olay_tarihi_saati": "YYYY-MM-DD HH:MM:SS" (Tahmini saat bilgisiyle)
    - "guncel_durum": "Yangın kontrol altına alındı, soğutma çalışmaları devam ediyor" gibi en son durum bilgisi.
    - "tesis_adi_ticari_unvan": "Haberdeki ismi, Ticaret Sicil veya LinkedIn gibi kaynaklarla teyit ederek bulduğun tam ve resmi ticari unvan."
    - "sehir_ilce": "İl, İlçe"
    - "olay_tipi_ozet": "Kısa ve profesyonel olay tanımı."
    - "hasar_tahmini": {{"tutar_araligi_tl": "Örn: 15-25 Milyon TL", "kaynak": "Haber metninde belirtildi / Ekspere dayalı tahmin", "aciklama": "Kritik makinelerin ve stokların durumu hakkında detay."}}
    - "can_kaybi_ve_yaralilar": {{"durum": "Evet / Hayır / Bilinmiyor", "detaylar": "Varsa ölen veya yaralanan kişilerin isimleri ve sayıları."}}
    - "sigorta_teminatlari_analizi": {{"potansiyel_teminatlar": ["Yangın", "Kar Kaybı (BI)", "Enkaz Kaldırma"], "notlar": "Poliçe detaylarına göre değişebilecek profesyonel notlar."}}
    - "cevre_tesis_analizi": [{{"tesis_adi": "Komşu Tesis A.Ş.", "risk_faktoru": "Yüksek/Orta/Düşük", "aciklama": "Sıçrama, duman gibi risklerin analizi."}}]
    - "kaynak_linkleri": ["{url}", "https://buldugun.diger.kaynak/linki"]
    - "gorsel_linkleri": ["https://haberdeki.resim.linki/image.jpg"]
    - "latitude": Ondalık formatta enlem.
    - "longitude": Ondalık formatta boylam.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.2)
        content = response.choices[0].message.content.strip()
        # Modellerin bazen JSON'u ```json ... ``` bloğu içine koyma eğilimi vardır.
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception:
        return None
        
# ------------------------------------------------------------------------------
# 4. YARDIMCI FONKSİYONLAR VE GÖRSEL ARAYÜZ
# ------------------------------------------------------------------------------

def parse_damage_to_radius(damage_str):
    if not isinstance(damage_str, str): return 100
    numbers = [int(s) for s in re.findall(r'\d+', damage_str)]
    if not numbers: return 100
    avg_damage = sum(numbers) / len(numbers)
    if "milyar" in damage_str.lower(): multiplier = 1000
    elif "milyon" in damage_str.lower(): multiplier = 1
    elif "bin" in damage_str.lower(): multiplier = 0.01
    else: multiplier = 0.00001
    radius = (avg_damage * multiplier) * 20 + 200 # Temel bir ölçekleme
    return min(radius, 5000) # Maksimum yarıçap

st.header("📈 En Son Tespit Edilen Hasarlar")
if st.button("En Son 15 Olayı Bul ve Profesyonel Analiz Yap", type="primary", use_container_width=True):
    with st.spinner("1. Aşama: En son olaylar ve haber linkleri taranıyor..."):
        latest_events = find_latest_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not latest_events:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")
    else:
        st.success(f"**{len(latest_events)} adet potansiyel olay bulundu.** Şimdi her biri için derinlemesine analiz başlatılıyor...")
        
        all_event_details, progress_bar = [], st.progress(0, text="Analiz ilerlemesi...")
        for i, event in enumerate(latest_events):
            progress_text = f"2. Aşama: '{event.get('headline', 'Bilinmeyen Olay')}' haberi analiz ediliyor... ({i+1}/{len(latest_events)})"
            progress_bar.progress((i + 1) / len(latest_events), text=progress_text)
            event_details = analyze_single_event(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"], event.get('headline'), event.get('url'))
            if event_details: all_event_details.append(event_details)
        progress_bar.empty()
        
        if not all_event_details:
            st.warning("Olaylar bulundu ancak detaylı analiz sırasında bir sorun oluştu veya analiz sonucu geçerli formatta değildi.")
        else:
            events_df = pd.DataFrame(all_event_details)
            events_df['olay_tarihi_saati'] = pd.to_datetime(events_df['olay_tarihi_saati'], errors='coerce')
            events_df = events_df.sort_values(by='olay_tarihi_saati', ascending=False).reset_index(drop=True)

            st.subheader("Analiz Edilen Son Olaylar Raporu")
            for index, row in events_df.iterrows():
                row = row.fillna('') # Boş alanlarda hata almamak için
                with st.expander(f"**{row['olay_tarihi_saati'].strftime('%d %b %Y, %H:%M')} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**"):
                    st.subheader(row['olay_tipi_ozet'])
                    st.info(f"**Güncel Durum:** {row['guncel_durum']}")
                    
                    if row.get('gorsel_linkleri') and isinstance(row['gorsel_linkleri'], list) and row['gorsel_linkleri']:
                        st.image(row['gorsel_linkleri'][0], caption="Olay Yerinden Görüntü", use_column_width=True)

                    st.markdown("---")
                    col1, col2 = st.columns(2)
                    with col1:
                        hasar_tahmini = row.get('hasar_tahmini', {})
                        st.markdown(f"##### Hasar Tahmini: `{hasar_tahmini.get('tutar_araligi_tl', 'Belirtilmemiş')}`")
                        st.caption(f"Kaynak: {hasar_tahmini.get('kaynak', 'Bilinmiyor')}")
                        st.write(hasar_tahmini.get('aciklama', ''))
                        
                        can_kaybi = row.get('can_kaybi_ve_yaralilar', {})
                        if can_kaybi.get('durum', 'Bilinmiyor').lower() == 'evet':
                            st.error(f"**Can Kaybı / Yaralı:** {can_kaybi.get('detaylar', 'Detay belirtilmemiş.')}")

                    with col2:
                        sigorta = row.get('sigorta_teminatlari_analizi', {})
                        st.markdown("##### Potansiyel Sigorta Teminatları")
                        st.json(sigorta)

                    st.markdown("---")
                    st.markdown("##### Çevre Tesisler İçin Risk Analizi")
                    st.table(pd.DataFrame(row['cevre_tesis_analizi']))
                    
                    st.markdown("---")
                    st.markdown("##### Tıklanabilir Kaynak Linkleri")
                    links_md = "".join([f"- [{link.split('//')[-1].split('/')[0]}]({link})\n" for link in row.get('kaynak_linkleri', [])])
                    st.markdown(links_md)

            st.header("🗺️ Olayların Konumsal ve Büyüklük Dağılımı")
            map_df = events_df.dropna(subset=['latitude', 'longitude'])
            if not map_df.empty:
                map_center = [map_df['latitude'].mean(), map_df['longitude'].mean()]
                m = folium.Map(location=map_center, zoom_start=6, tiles="CartoDB positron")
                for _, row in map_df.iterrows():
                    hasar = row.get('hasar_tahmini', {})
                    radius = parse_damage_to_radius(hasar.get('tutar_araligi_tl', ''))
                    popup_html = f"""
                    <h6>{row['tesis_adi_ticari_unvan']}</h6>
                    <b>Durum:</b> {row['guncel_durum']}<br>
                    <b>Hasar Tahmini:</b> {hasar.get('tutar_araligi_tl', 'N/A')}
                    """
                    folium.Circle(
                        location=[row['latitude'], row['longitude']],
                        radius=radius,
                        color='crimson',
                        fill=True,
                        fill_color='crimson',
                        popup=folium.Popup(popup_html, max_width=300)
                    ).add_to(m)
                folium_static(m, width=None, height=600)
