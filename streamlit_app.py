# ==============================================================================
#  NİHAİ KOD (v35.0): Hibrit İstihbarat Protokolü
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
from newspaper import Article
from urllib.parse import quote

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")
st.markdown("---")

# --- API Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

# --- Session State Başlatma ---
if 'unique_events' not in st.session_state:
    st.session_state.unique_events = []
if 'report' not in st.session_state:
    st.session_state.report = None

# ------------------------------------------------------------------------------
# 2. VERİ TOPLAMA VE İŞLEME FONKSİYONLARI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=900)
def get_candidate_urls_from_rss():
    """Adım 1: Google News RSS'ten potansiyel olayların URL'lerini çeker."""
    search_query = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması")'
    rss_url = f"https://news.google.com/rss/search?q={quote(search_query)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        return [{"title": entry.title.split(" - ")[0], "url": entry.link} for entry in feed.entries[:20]]
    except Exception as e:
        st.error(f"RSS Hatası: {e}"); return []

@st.cache_data(ttl=3600)
def extract_full_text_from_url(url):
    """Adım 2: Verilen URL'den newspaper3k ile haberin tam metnini çeker."""
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception:
        return "" # Hata durumunda boş metin döndür

@st.cache_data(ttl=3600)
def group_and_deduplicate_events(_client, articles_with_text):
    """Adım 3 (AI Haber Editörü): Haber metinlerini okuyarak aynı olayları gruplar ve tekilleştirir."""
    prompt = f"""
    Sen bir haber editörüsün. Sana aşağıda başlıkları ve tam metinleri olan bir haber listesi veriyorum.
    GÖREVİN: Bu listedeki haberleri oku, aynı olaya ait olanları tespit et ve her bir benzersiz olay için tek bir temsilci oluşturarak bana temiz, gruplanmış bir liste sun.
    
    HABER LİSTESİ:
    {json.dumps(articles_with_text, ensure_ascii=False, indent=2)}

    ÇIKTI FORMATI:
    Bana SADECE bir JSON dizisi (array) döndür. Her bir nesne, benzersiz bir olayı temsil etmeli ve şu anahtarlara sahip olmalı:
    - "olay_basligi": Olayı en iyi özetleyen başlık.
    - "birincil_url": Olayla ilgili en güvenilir veya detaylı haberin linki.
    - "tam_metin": Olayla ilgili en kapsamlı metin (genellikle en uzun olanı seç).

    Örnek Çıktı:
    [
      {{
        "olay_basligi": "Kocaeli Dilovası'nda Kimya Fabrikasında Yangın",
        "birincil_url": "https://...bir-haber-linki...",
        "tam_metin": "Kocaeli'nin Dilovası ilçesinde bulunan Kömürcüler OSB'deki bir kimya fabrikasında..."
      }},
      {{
        "olay_basligi": "İzmir Kemalpaşa'daki Depoda Patlama",
        "birincil_url": "https://...baska-haber-linki...",
        "tam_metin": "İzmir'in Kemalpaşa ilçesindeki bir sanayi sitesinde bulunan depoda..."
      }}
    ]
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.0)
        content = response.choices[0].message.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception as e:
        st.error(f"AI Editör Hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. İSTİHBARAT ANALİSTİ AI ZİNCİRİ
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def extract_clues_from_text(_client, full_text):
    """Aşama A (İpucu Çıkarıcı): Tam metinden X'te aranacak ipuçlarını çıkarır."""
    prompt = f"GÖREV: Aşağıdaki haber metnini oku ve X'te arama yapmak için kullanılabilecek en spesifik ipuçlarını çıkar. Çıktıyı SADECE JSON formatında ver.\nHABER METNİ: \"{full_text}\"\n\nJSON YAPISI: {{\"en_spesifik_konum\": \"...\", \"tesis_tipi\": \"...\", \"olay_detaylari\": \"...\"}}"
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=1024, temperature=0.0)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception: return {}

@st.cache_data(ttl=3600)
def simulate_x_search_for_name(_client, clues):
    """Aşama B (Nokta Atışı X Simülasyonu): İpuçlarıyla kontrollü X araması simüle eder."""
    prompt = f"""
    Sen bir OSINT (Açık Kaynak İstihbaratı) uzmanısın. Görevin, sana verilen ipuçlarını kullanarak X (Twitter) üzerinde nokta atışı bir arama simülasyonu yapmak ve olayın yaşandığı tesisin ticari unvanını teyit etmektir. ASLA TAHMİN YÜRÜTME. KANITA DAYALI OL.

    İPUÇLARI:
    - Konum: {clues.get('en_spesifik_konum')}
    - Tesis Tipi: {clues.get('tesis_tipi')}
    - Olay Detayları: {clues.get('olay_detaylari')}

    SİMÜLASYON ADIMLARI:
    1. Bu ipuçlarıyla en etkili X arama sorgularını zihninde oluştur.
    2. Bu sorguların sonuçlarında ortaya çıkacak olan yerel haber hesapları, görgü tanıkları veya resmi kurum paylaşımlarını değerlendir.
    3. Farklı kaynakların aynı ismi teyit edip etmediğini kontrol et.

    ÇIKTI FORMATI (SADECE JSON):
    {{"tesis_adi": "Yüksek kesinlikle bulunan isim VEYA 'Teyit Edilemedi'", "kanit": "İsmi nasıl bulduğunun açıklaması. Örn: 'Yerel X haber hesabı @... ve görgü tanığı paylaşımları ABC Boya A.Ş. ismini teyit etmektedir.' VEYA 'Aramalar sonucunda spesifik bir firma adı üzerinde fikir birliğine varılamadı.'"}}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except Exception: return {}

@st.cache_data(ttl=3600)
def generate_final_report(_client, full_text, company_info):
    """Aşama C (Nihai Raporlayıcı): Tüm bilgileri birleştirip son raporu oluşturur."""
    prompt = f"""
    Sen elit bir sigorta risk analistisin. Bir olayla ilgili aşağıdaki bilgilere sahipsin:
    - TEYİT EDİLMİŞ TESİS BİLGİSİ: {company_info}
    - OLAYIN YAŞANDIĞI HABERİN TAM METNİ: \"{full_text}\"

    GÖREVİN: Bu bilgileri kullanarak, daha önceki versiyonlarla aynı formatta olan, aşağıdaki tüm anahtarları dolduran nihai ve detaylı JSON raporunu oluştur. Özellikle koordinatları metindeki konumdan tahmin etmeye çalış.

    JSON YAPISI: "sehir_ilce", "tahmini_koordinat": {{"lat": "...", "lon": "..."}}, "maddi_hasar_fiziksel_boyut", "is_durmasi_kar_kaybi", "hasarin_nedeni", "yapilan_mudahale", "guncel_durum", "cevreye_etki", "gorsel_url"
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        match = re.search(r'\{.*\}', response.choices[0].message.content, re.DOTALL)
        final_data = json.loads(match.group(0)) if match else {}
        final_data.update(company_info) # Tesis adı ve kanıtı rapora ekle
        return final_data
    except Exception: return {}

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon):
    """Google Places API ile komşu tesisleri bulur."""
    if not all([api_key, lat, lon]): return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=500&type=establishment&keyword=fabrika|depo|sanayi|tesis&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity'), "lat": p.get('geometry',{}).get('location',{}).get('lat'),"lng": p.get('geometry',{}).get('location',{}).get('lng')} for p in results[:10]]
    except Exception: return []

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------

col_list, col_detail = st.columns([1, 2], gap="large")

with col_list:
    st.header("📰 Olaylar")
    if st.button("Yeni Olayları Tara ve Grupla", type="primary", use_container_width=True):
        st.session_state.unique_events = []
        st.session_state.report = None
        with st.spinner("Haberler taranıyor, metinler çekiliyor ve gruplanıyor... (1-2 dk)"):
            candidates = get_candidate_urls_from_rss()
            if candidates:
                articles_with_text = []
                for candidate in candidates:
                    text = extract_full_text_from_url(candidate['url'])
                    if text and len(text) > 200: # Sadece yeterince uzun metinleri dikkate al
                        articles_with_text.append({"title": candidate['title'], "url": candidate['url'], "full_text": text[:4000]}) # Metni kısaltarak API'ye gönder
                
                if articles_with_text:
                    st.session_state.unique_events = group_and_deduplicate_events(client, articles_with_text)

    if not st.session_state.unique_events:
        st.info("Görüntülenecek olay bulunamadı. Lütfen yeni bir tarama başlatın.")
    else:
        event_titles = [event['olay_basligi'] for event in st.session_state.unique_events]
        selected_title = st.radio("Analiz için bir olay seçin:", event_titles, key="event_selector")
        
        # Seçilen olayı session state'de sakla
        st.session_state.selected_event = next((event for event in st.session_state.unique_events if event['olay_basligi'] == selected_title), None)


with col_detail:
    st.header("📝 Analiz Raporu")
    selected_event = st.session_state.get('selected_event')

    if not selected_event:
        st.info("Lütfen sol menüden bir olay seçin ve analiz sürecini başlatın.")
    else:
        st.subheader(f"Seçilen Olay: {selected_event['olay_basligi']}")
        if st.button("Seçili Olayı Derinlemesine Analiz Et", type="primary", use_container_width=True):
            if not all([client, google_api_key]):
                st.error("Grok ve Google API anahtarları eksik!")
            else:
                with st.status("İstihbarat Analisti Protokolü yürütülüyor...", expanded=True) as status:
                    # Aşama A
                    status.write("Aşama A: Haber metninden ipuçları çıkarılıyor...")
                    clues = extract_clues_from_text(client, selected_event['tam_metin'])
                    if not clues: status.update(label="İpucu çıkarılamadı!", state="error"); st.stop()

                    # Aşama B
                    status.write("Aşama B: İpuçları ile X'te kontrollü arama simüle ediliyor...")
                    company_info = simulate_x_search_for_name(client, clues)
                    if not company_info or company_info.get('tesis_adi') == 'Teyit Edilemedi':
                        st.error(f"Tesis Adı Teyit Edilemedi. Kanıt: {company_info.get('kanit', 'N/A')}")
                        status.update(label="Tesis Adı Bulunamadı!", state="error"); st.stop()

                    # Aşama C
                    status.write(f"Aşama C: Tesis '{company_info['tesis_adi']}' olarak teyit edildi! Nihai rapor oluşturuluyor...")
                    report_data = generate_final_report(client, selected_event['tam_metin'], company_info)
                    
                    if report_data:
                        report_data['kaynak_url'] = selected_event['birincil_url']
                        coords = report_data.get('tahmini_koordinat', {})
                        lat, lon = coords.get('lat'), coords.get('lon')
                        if lat and lon:
                           report_data['komsu_tesisler'] = find_neighboring_facilities(google_api_key, lat, lon)
                        st.session_state.report = report_data
                        status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
                    else:
                        st.session_state.report = None
                        status.update(label="Nihai Rapor Oluşturulamadı!", state="error")

    # Raporu Görüntüle
    if st.session_state.get('report'):
        report = st.session_state.report
        st.subheader(f"Rapor: {report.get('tesis_adi', 'İsimsiz Tesis')}")
        st.info(f"**Kanıt:** *\"{report.get('kanit', 'Kanıt bulunamadı.')}\"*")
        if report.get('gorsel_url'): st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (Tahmini)")
        
        st.markdown("##### Hasar Analizi")
        col_m, col_k = st.columns(2)
        with col_m: st.warning(f"**Maddi Hasar (Fiziksel Boyut):** {report.get('maddi_hasar_fiziksel_boyut', 'Detay Yok')}")
        with col_k: st.error(f"**İş Durması / Kar Kaybı:** {report.get('is_durmasi_kar_kaybi', 'Detay Yok')}")

        st.markdown("##### Olay Yönetimi ve Etkileri")
        st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'Detay Yok')}")
        st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'Detay Yok')}")
        st.caption(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'Detay Yok')}")
        st.caption(f"**Çevreye Etki:** {report.get('cevreye_etki', 'Detay Yok')}")

        with st.expander("🗺️ Harita, Komşu Tesisler ve Kaynak Link", expanded=True):
            coords = report.get('tahmini_koordinat', {})
            lat, lon = coords.get('lat'), coords.get('lon')
            if lat and lon:
                try:
                    m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                    folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                    neighbors = report.get('komsu_tesisler', [])
                    for n in neighbors:
                        if n.get('lat') and n.get('lng'):
                            folium.Marker([n['lat'], n['lng']], popup=f"<b>{n['tesis_adi']}</b>", tooltip=n['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                    folium_static(m, height=400)
                    st.markdown("<h6>Komşu Tesisler (Google Harita Verisi)</h6>", unsafe_allow_html=True)
                    st.table(pd.DataFrame(neighbors)[['tesis_adi', 'tip', 'konum']])
                except (ValueError, TypeError): st.warning("Koordinat formatı geçersiz.")
            else:
                st.info("Bu rapor için harita verisi bulunamadı.")
            st.markdown(f"**Haber Kaynağı:** [Link]({report.get('kaynak_url')})")
