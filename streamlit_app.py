# ==============================================================================
#      NİHAİ KOD (v24.0): Adım Adım Teyit Mimarisi
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests
import feedparser
from urllib.parse import quote

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
def get_latest_event_candidate_from_rss():
    search_query = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması" OR "enerji santrali")'
    encoded_query = quote(search_query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        latest_entry = feed.entries[0]
        return {"headline": latest_entry.title, "url": latest_entry.link}
    except Exception as e:
        st.error(f"RSS haber kaynağına erişilirken hata oluştu: {e}"); return None

# YENİ ADIM 1: "Dedektif" AI - Sadece Tesis Adını ve Kanıtını Bulur
@st.cache_data(ttl=3600)
def find_company_name_with_proof(_client, event_candidate):
    prompt = f"""
    Sen bir istihbarat dedektifisin. Tek bir görevin var: '{event_candidate['headline']}' başlıklı ve '{event_candidate['url']}' adresindeki haberde adı geçen **spesifik ticari unvanı (şirket adını)** bulmak.
    
    1.  Öncelikle X (Twitter)'da haber başlığındaki anahtar kelimelerle arama yap. Genellikle gazeteciler veya resmi hesaplar şirket adını burada verir.
    2.  Bulamazsan, haber metnini dikkatlice oku.
    3.  Bulduğun şirket adını ve bu adı bulduğun **orijinal cümlenin birebir alıntısını (kanıt)** bir JSON nesnesi olarak döndür.
    4.  Eğer %95 emin değilsen veya isim bulamazsan, 'tesis_adi' alanına 'Tespit Edilemedi' yaz. ASLA İSİM UYDURMA.

    ÇIKTI FORMATI: {{"tesis_adi": "...", "kanit": "..."}}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=1024, temperature=0.0)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else {"tesis_adi": "Tespit Edilemedi", "kanit": "AI yanıt formatı bozuk."}
    except Exception as e:
        st.error(f"Dedektif AI hatası: {e}"); return None

# YENİ ADIM 2: "Analist" AI - Teyit Edilmiş Bilgiyle Raporu Doldurur
@st.cache_data(ttl=3600)
def get_detailed_report(_client, event_candidate, verified_name, proof):
    prompt = f"""
    Sen elit bir sigorta istihbarat analistisin. Analiz edeceğin olayın ana tesisi teyit edildi.
    - Teyit Edilmiş Tesis Adı: **{verified_name}**
    - Kanıt: *"{proof}"*
    - Haber Linki: {event_candidate['url']}

    GÖREVİN: Bu teyit edilmiş bilgi ışığında, verdiğim linkteki haberi ve web'deki diğer kaynakları kullanarak aşağıdaki tüm detayları içeren zengin bir JSON raporu oluştur.
    
    JSON NESNE YAPISI:
    - "sehir_ilce", "olay_tarihi", "hasarin_nedeni", "hasarin_fiziksel_boyutu", "yapilan_mudahale",
    - "hasar_tahmini_detay": Maddi hasar ve/veya kar kaybı tahmini ve kaynağı.
    - "guncel_durum", "cevreye_etki", "latitude", "longitude",
    - "gorsel_url": Olayla ilgili en net fotoğrafın doğrudan URL'si (.jpg, .png).
    - "kaynak_urller": Kullandığın tüm linklerin listesi.
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\{.*\}', content, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as e:
        st.error(f"Analist AI hatası: {e}"); return None

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    #... (Bu fonksiyon aynı kalıyor)
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        neighbors = []
        for p in results[:10]:
            loc = p.get('geometry', {}).get('location', {})
            neighbors.append({"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "lat": loc.get('lat'), "lng": loc.get('lng')})
        return neighbors
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Tek Olay Analizi")
run_analysis = st.sidebar.button("En Son Önemli Olayı Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En güncel ve önemli tek bir olayı bulur, adını teyit eder ve detaylı analiz eder.")

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    report = None
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1: Haber kaynakları taranıyor ve en güncel olay adayı bulunuyor...")
        event_candidate = get_latest_event_candidate_from_rss()
        
        if not event_candidate:
            status.update(label="Hata! Uygun bir olay adayı bulunamadı.", state="error"); st.stop()
        
        status.write(f"Olay Adayı Bulundu: **{event_candidate['headline']}**")
        status.write("Aşama 2: 'Dedektif AI' çalıştırılıyor: Tesis adı ve kanıt aranıyor...")
        
        name_proof = find_company_name_with_proof(client, event_candidate)

        if not name_proof or name_proof.get('tesis_adi') == 'Tespit Edilemedi':
            status.update(label="Tesis Adı Bulunamadı!", state="error")
            st.error(f"Bu olay için spesifik bir tesis adı teyit edilemedi. Kanıt: {name_proof.get('kanit', 'N/A')}")
        else:
            verified_name = name_proof['tesis_adi']
            proof = name_proof['kanit']
            status.write(f"Tesis Adı Teyit Edildi: **{verified_name}**")
            status.write("Aşama 3: 'Analist AI' çalıştırılıyor: Detaylı rapor oluşturuluyor...")

            report = get_detailed_report(client, event_candidate, verified_name, proof)
            
            if report:
                report['tesis_adi'] = verified_name # Teyit edilmiş ismi rapora ekle
                report['tesis_adi_kanit'] = proof
                status.write("Aşama 4: Rapor zenginleştiriliyor: Google Maps'ten komşu tesis verileri çekiliyor...")
                report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
                status.update(label="Analiz Başarıyla Tamamlandı!", state="complete")
            else:
                status.update(label="Detaylı Analiz Başarısız Oldu!", state="error")

    if report:
        st.markdown("---")
        st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        
        if report.get('gorsel_url'):
            st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (AI Tarafından Bulundu)")

        st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"*")
        
        col1, col2 = st.columns(2)
        with col1:
            st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
        with col2:
            st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")

        st.metric(label="Maddi Hasar ve/veya Kar Kaybı Tahmini", value=report.get('hasar_tahmini_detay', 'Tespit Edilemedi'))
        st.info(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Tespit Edilemedi.')}")

        with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
            # ... Harita ve komşu tesis gösterme kodu (v23 ile aynı)
            lat, lon = report.get('latitude'), report.get('longitude')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    neighbors = report.get('komsu_tesisler_harita', [])
                    for neighbor in neighbors:
                        if neighbor.get('lat') and neighbor.get('lng'):
                            folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b><br><i>Tip: {neighbor['tip']}</i>", tooltip=neighbor['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=500)
                except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı.")
            else:
                st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

            st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
            st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
            st.markdown("##### Kaynak Linkler")
            for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak en son olayın analizini başlatın.")
