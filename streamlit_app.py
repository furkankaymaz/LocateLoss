# ==============================================================================
#           NİHAİ KOD (v8.1): f-string SÖZDİZİMİ DÜZELTMESİ
# ==============================================================================
import streamlit as st
import pandas as pd
from datetime import datetime
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import base64 # Resimleri pop-up'a gömmek için

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
def find_latest_events(key, base_url, model, event_count=1): # DEBUG: event_count=1 olarak ayarlandı
    client = OpenAI(api_key=key, base_url=base_url)
    current_date = datetime.now().strftime('%Y-%m-%d')
    prompt = f"""
    Bugünün tarihi {current_date}. Türkiye'de son 3 ay içinde yaşanmış endüstriyel hasar olaylarını (fabrika yangını, patlama vb.) tara.
    Bulduğun olaylar arasından bana **en güncel {event_count} tanesini** listele. Özellikle son 72 saatteki olaylara öncelik ver.
    Öncelikli kaynakların X (Twitter)'daki resmi hesaplar (valilik, itfaiye) ve ulusal haber ajansları (AA, DHA) olsun.
    # DÜZELTME: f-string içinde literal {} kullanmak için {{}} kullanılır.
    Çıktıyı, {{"headline": "...", "url": "..."}} anahtarlarını içeren bir JSON dizisi olarak ver. Sadece listele.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=512, temperature=0.0)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception:
        return []

@st.cache_data(ttl=86400)
def analyze_single_event(key, base_url, model, headline, url):
    client = OpenAI(api_key=key, base_url=base_url)
    # DÜZELTME: f-string içindeki tüm JSON örnekleri {{ ve }} ile güncellendi.
    prompt = f"""
    Sen bir sigorta hasar eksperisin. Sana verilen şu haberi analiz et: "{headline}" ({url}).
    GÖREVİN: X (Twitter) ve diğer haber ajanslarını kullanarak bu tek olayı çapraz kontrol et ve aşağıdaki JSON formatında detaylı bir rapor oluştur.
    ÖNCELİK: Haberde veya X paylaşımlarında geçen **firma adını** tam ve doğru olarak tespit et. Karmaşık teyitlere (ticaret sicil vb.) gerek yok, sadece kaynaklarda belirtilen ismi bul.

    JSON ÇIKTI FORMATI:
    - "olay_tarihi_saati": "YYYY-MM-DD HH:MM:SS"
    - "guncel_durum": "Yangın kontrol altına alındı, soğutma çalışmaları devam ediyor" gibi en son durum bilgisi.
    - "tesis_adi_ticari_unvan": "Haberde geçen en doğru ve tam firma adı."
    - "sehir_ilce": "İl, İlçe"
    - "olay_tipi_ozet": "Kısa ve profesyonel olay tanımı."
    - "hasar_tahmini": {{"tutar_araligi_tl": "Örn: 15-25 Milyon TL", "kaynak": "Haber metninde belirtildi / Ekspere dayalı tahmin", "aciklama": "Kritik makinelerin ve stokların durumu hakkında detay."}}
    - "can_kaybi_ve_yaralilar": {{"durum": "Evet / Hayır / Bilinmiyor", "detaylar": "Varsa ölen veya yaralanan kişilerin isimleri ve sayıları."}}
    - "cevre_tesis_analizi": [{{"tesis_adi": "Komşu Tesis A.Ş.", "risk_faktoru": "Yüksek/Orta/Düşük", "aciklama": "Sıçrama, duman gibi risklerin analizi."}}]
    - "kaynak_linkleri": ["{url}", "https://buldugun.diger.kaynak/linki"]
    - "gorsel_linkleri": ["https://haberdeki.resim.linki/image.jpg"]
    - "latitude": Ondalık formatta enlem.
    - "longitude": Ondalık formatta boylam.

    SON KONTROL: Raporu oluşturduktan sonra, tüm alanların (özellikle firma adı ve hasar tahmini) haber kaynaklarıyla tutarlı olduğunu son bir kez kontrol et.
    """
    try:
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception:
        return None

# ------------------------------------------------------------------------------
# 4. GÖRSEL ARAYÜZ
# ------------------------------------------------------------------------------
st.header("📈 En Son Tespit Edilen Hasarlar (Test Modu: Son 1 Olay)")

if st.button("En Son Olayı Bul ve Analiz Et", type="primary", use_container_width=True):
    with st.spinner("1. Aşama: En son olay taranıyor..."):
        latest_events = find_latest_events(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"])

    if not latest_events:
        st.info("Belirtilen kriterlere uygun, raporlanacak bir endüstriyel olay tespit edilemedi.")
    else:
        st.success(f"**1 adet potensiyel olay bulundu.** Şimdi derinlemesine analiz ediliyor...")

        event = latest_events[0]
        event_details = analyze_single_event(api_key, SELECTED_CONFIG["base_url"], SELECTED_CONFIG["model"], event.get('headline'), event.get('url'))

        if not event_details:
            st.warning("Olay bulundu ancak detaylı analiz sırasında bir sorun oluştu veya analiz sonucu geçerli formatta değildi.")
        else:
            events_df = pd.DataFrame([event_details]) # Tek olaylık bir DataFrame oluştur
            events_df['olay_tarihi_saati'] = pd.to_datetime(events_df['olay_tarihi_saati'], errors='coerce')
            st.subheader("Analiz Edilen Son Olay Raporu")

            row = events_df.iloc[0].fillna('') # Tek satırı al
            with st.expander(f"**{row['olay_tarihi_saati'].strftime('%d %b %Y, %H:%M')} - {row['tesis_adi_ticari_unvan']} ({row['sehir_ilce']})**", expanded=True):
                st.subheader(row['olay_tipi_ozet'])
                st.info(f"**Güncel Durum:** {row['guncel_durum']}")

                gorsel_linkleri = row.get('gorsel_linkleri')
                if gorsel_linkleri and isinstance(gorsel_linkleri, list) and gorsel_linkleri[0]:
                    st.image(gorsel_linkleri[0], caption="Olay Yerinden Görüntü", use_column_width=True)

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
                    # sigorta teminatları kaldırıldı, prompt'ta da yoktu.
                    # Eğer istenirse tekrar eklenebilir.
                    st.markdown("##### Çevre Tesisler İçin Risk Analizi")
                    st.table(pd.DataFrame(row.get('cevre_tesis_analizi',[])))

                st.markdown("---"); st.markdown("##### Tıklanabilir Kaynak Linkleri")
                links_md = "".join([f"- [{link.split('//')[-1].split('/')[0]}]({link})\n" for link in row.get('kaynak_linkleri', [])])
                st.markdown(links_md)

            # --- YENİ VE GELİŞTİRİLMİŞ HARİTA ---
            st.header("🗺️ Olay Yeri İncelemesi")
            map_df = events_df.dropna(subset=['latitude', 'longitude'])
            if not map_df.empty:
                row = map_df.iloc[0]
                map_center = [row['latitude'], row['longitude']]
                m = folium.Map(location=map_center, zoom_start=15, tiles="CartoDB positron")

                # Zengin HTML Pop-up içeriği oluşturma
                gorsel_html = ""
                if gorsel_linkleri and isinstance(gorsel_linkleri, list) and gorsel_linkleri[0]:
                    gorsel_html = f'<img src="{gorsel_linkleri[0]}" width="280"><br>'

                komsu_tesisler_html = "<h6>Komşu Tesis Riskleri:</h6><ul>"
                for tesis in row.get('cevre_tesis_analizi', []):
                    komsu_tesisler_html += f"<li><b>{tesis.get('tesis_adi')}</b>: {tesis.get('risk_faktoru')}</li>"
                komsu_tesisler_html += "</ul>"

                popup_html = f"""
                <div style="font-family: Arial; max-width: 300px;">
                    {gorsel_html}
                    <h4>{row['tesis_adi_ticari_unvan']}</h4>
                    <p><b>Durum:</b> {row['guncel_durum']}</p>
                    <p><b>Hasar Tahmini:</b> {row.get('hasar_tahmini', {{}}).get('tutar_araligi_tl', 'N/A')}</p>
                    <hr>
                    {komsu_tesisler_html}
                </div>
                """
                iframe = folium.IFrame(popup_html, width=320, height=400)
                popup = folium.Popup(iframe, max_width=320)

                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    popup=popup,
                    tooltip=row['tesis_adi_ticari_unvan'],
                    icon=folium.Icon(color='red', icon='fire')
                ).add_to(m)

                folium_static(m, width=None, height=500)
