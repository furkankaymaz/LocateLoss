# ==============================================================================
#  NİHAİ KOD (v36.0): Gelişmiş Metin Çıkarma ve Sağlamlaştırılmış AI Mimarisi
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
from urllib.parse import quote, urlparse
import time

# Gelişmiş metin çıkarma kütüphaneleri
import trafilatura
from bs4 import BeautifulSoup
import readability

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
# 2. ÇEKİRDEK FONKSİYONLAR (TÜMÜ YENİLENDİ VE GÜÇLENDİRİLDİ)
# ------------------------------------------------------------------------------

# Adım 1: Geliştirilmiş RSS Fonksiyonu
@st.cache_data(ttl=600)
def get_latest_event_candidate_from_rss():
    """Tarihe göre sıralanmış ve tekilleştirilmiş en güncel haberi bulur."""
    q = '("fabrika yangını" OR "sanayi tesisi" OR "OSB yangın" OR "liman kaza" OR "depo patlaması" OR "enerji santrali")'
    rss_url = f"https://news.google.com/rss/search?q={quote(q)}+when:7d&hl=tr&gl=TR&ceid=TR:tr"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None
        
        seen = set()
        entries = sorted(feed.entries, key=lambda e: getattr(e, "published_parsed", time.gmtime(0)), reverse=True)
        
        for e in entries:
            title = getattr(e, "title", "").strip().split(" - ")[0]
            link = getattr(e, "link", "").strip()
            dom = urlparse(link).netloc
            key = (title.lower(), dom)
            if key in seen or "news.google.com" in dom: continue
            
            seen.add(key)
            return {"headline": title, "url": link}
        return None
    except Exception as e:
        st.error(f"RSS erişim hatası: {e}"); return None

# Adım 2A: Katmanlı Metin Çıkarma Motoru
def fetch_article_text(url: str, timeout: int = 15) -> str:
    """Bir haber URL'sinden ana metni çıkarır. Sıra: trafilatura -> readability -> bs4."""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        resp.raise_for_status()
        html_doc = resp.text
    except requests.exceptions.RequestException:
        return ""

    # 1. Katman: Trafilatura (En Güçlü)
    extracted = trafilatura.extract(html_doc, include_comments=False, include_tables=False)
    if extracted and len(extracted.strip()) > 300:
        return extracted.strip()

    # 2. Katman: Readability (İkinci Tercih)
    try:
        doc = readability.Document(html_doc)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = soup.get_text(separator="\n", strip=True)
        if text and len(text.strip()) > 300:
            return text.strip()
    except Exception:
        pass

    # 3. Katman: BeautifulSoup (Temel Fallback)
    try:
        soup = BeautifulSoup(html_doc, "lxml")
        for element in soup(["script", "style", "header", "footer", "nav", "aside"]):
            element.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = "\n".join([p for p in paragraphs if len(p) > 50])
        return text.strip()
    except Exception:
        return ""

# Adım 2B: "Araştırmacı" AI - Çekilen METİNDEN özet çıkarır
@st.cache_data(ttl=3600)
def get_summary_from_text(_client, url):
    raw_text = fetch_article_text(url)
    if not raw_text or len(raw_text) < 300:
        st.error(f"Makale metni çekilemedi veya yetersiz. URL ({url}) erişilemez veya içeriği boş olabilir.")
        return None
    
    article_text = raw_text[:12000] # Token sınırını aşmamak için metni kısalt

    prompt = f"""
    Aşağıdaki metin bir haber web sayfasından alınmıştır. Metni dikkatlice oku ve olayın tüm detaylarını (ne, nerede, ne zaman, neden, sonuçları) içeren, tarafsız ve kapsamlı bir özet metin oluştur.

    HABER METNİ:
    {article_text}
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.0
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Araştırmacı AI (Özet Çıkarma) Hatası: {e}"); return None

# Adım 3: Geliştirilmiş "Analist" AI ve Güvenli JSON Çıkarımı
def extract_json_strict(text: str):
    """AI yanıtından JSON'ı güvenli bir şekilde çıkarır."""
    if not text: return None
    try: # Önce doğrudan parse etmeyi dene, en temiz yöntem
        return json.loads(text)
    except json.JSONDecodeError: # Başarısız olursa, metin içindeki bloğu ara
        match = re.search(r'\{.*\}', text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None

@st.cache_data(ttl=3600)
def get_detailed_report_from_summary(_client, headline, summary_text):
    prompt = f"""
    Sen elit bir sigorta istihbarat analistisin. Görevin, sana verilen özeti ve başlıktaki ipuçlarını kullanarak X (Twitter) üzerinde zihinsel bir araştırma yapmak ve aşağıdaki JSON şemasına %100 uyacak şekilde bir rapor oluşturmaktır. Bilmediğin alanlara "Tespit Edilemedi" yaz. ASLA bilgi uydurma.

    BAŞLIK: "{headline}"
    ÖZET METNİ: "{summary_text}"

    JSON ŞEMASI (SADECE BU FORMATTA ÇIKTI VER, AÇIKLAMA EKLEME):
    {{
      "tesis_adi": "string", "tesis_adi_kanit": "string", "sehir_ilce": "string", "olay_tarihi": "string",
      "hasarin_nedeni": "string", "hasarin_fiziksel_boyutu": "string", "yapilan_mudahale": "string",
      "maddi_hasar_tahmini": "string", "kar_kaybi_tahmini": "string", "guncel_durum": "string",
      "cevreye_etki": "string", "latitude": "string", "longitude": "string", "gorsel_url": "string"
    }}
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=4096, temperature=0.1)
        content = response.choices[0].message.content
        data = extract_json_strict(content)
        if data:
            return data
        else:
            st.error(f"Analist AI geçerli bir JSON üretemedi. Ham yanıt: {content}"); return None
    except Exception as e:
        st.error(f"Analist AI (Rapor Oluşturma) Hatası: {e}"); return None

# Adım 4: Geliştirilmiş Coğrafi Zenginleştirme
@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=1800):
    if not api_key or not lat or not lon: return []
    try:
        kw = quote("fabrika depo sanayi tesis OSB üretim")
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={int(radius)}&type=establishment&keyword={kw}&key={api_key}"
        response = requests.get(url, timeout=12)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "adres": p.get('vicinity'), "lat": p.get('geometry', {}).get('location', {}).get('lat'), "lng": p.get('geometry', {}).get('location', {}).get('lng')} for p in results[:15]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []


# ------------------------------------------------------------------------------
# 3. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
# (Bu kısım önceki kodla büyük ölçüde aynı, sadece fonksiyon isimleri güncellendi)

st.sidebar.header("Tek Olay Analizi")
run_analysis = st.sidebar.button("En Son Önemli Olayı Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En güncel olayı bulur, içeriğini çeker, özetler ve detaylı analiz eder.")

if 'report' not in st.session_state:
    st.session_state.report = None

if run_analysis:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()

    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1/4: Haber kaynakları taranıyor...")
        event_candidate = get_latest_event_candidate_from_rss()
        if not event_candidate:
            status.update(label="Hata! Uygun bir olay adayı bulunamadı.", state="error"); st.stop()
        
        status.write(f"Olay Adayı Bulundu: **{event_candidate['headline']}**")
        status.write(f"Aşama 2/4: 'Araştırmacı AI' çalışıyor: Haber içeriği çekiliyor ve özetleniyor...")
        
        summary_text = get_summary_from_text(client, event_candidate['url'])
        if not summary_text:
            status.update(label="Hata! Haber metni çekilemedi veya özetlenemedi.", state="error"); st.stop()

        status.write("Aşama 3/4: 'Analist AI' çalışıyor: Özetlenmiş metinden detaylı rapor oluşturuluyor...")
        report = get_detailed_report_from_summary(client, event_candidate['headline'], summary_text)
        
        if report:
            report['kaynak_url'] = event_candidate['url']
            status.write("Aşama 4/4: Rapor zenginleştiriliyor: Google Maps verileri çekiliyor...")
            report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
            st.session_state.report = report
            status.update(label="Analiz Başarıyla Tamamlandı!", state="complete", expanded=False)
        else:
            st.session_state.report = None
            status.update(label="Analiz Başarısız Oldu!", state="error")

if st.session_state.report:
    report = st.session_state.report
    # (Rapor gösterme kodunda değişiklik yok, önceki haliyle çalışacaktır)
    st.markdown("---")
    st.header(f"Analiz Raporu: {report.get('tesis_adi', 'İsimsiz Tesis')}")
    if report.get('gorsel_url') and 'http' in report.get('gorsel_url'):
        st.image(report['gorsel_url'], caption="Olay Yerinden Görüntü (AI Tarafından Bulundu)")
    st.info(f"**Kanıt:** *\"{report.get('tesis_adi_kanit', 'Kanıt bulunamadı.')}\"*")
    
    st.subheader("Hasar ve Olay Detayları")
    col1, col2 = st.columns(2)
    with col1:
        st.warning(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
        st.warning(f"**Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
    with col2:
        st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
        st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
    
    st.subheader("Finansal Etki Tahmini")
    col3, col4 = st.columns(2)
    with col3: st.metric(label="Maddi Hasar Tahmini", value=report.get('maddi_hasar_tahmini', 'Tespit Edilemedi'))
    with col4: st.metric(label="Kar Kaybı Tahmini", value=report.get('kar_kaybi_tahmini', 'Tespit Edilemedi'))
    
    with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle", expanded=True):
        lat, lon = report.get('latitude'), report.get('longitude')
        if lat and lon:
            try:
                m = folium.Map(location=[float(lat), float(lon)], zoom_start=14, tiles="CartoDB positron")
                folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                neighbors = report.get('komsu_tesisler_harita', [])
                for neighbor in neighbors:
                    if neighbor.get('lat') and neighbor.get('lng'):
                        folium.Marker([neighbor['lat'], neighbor['lng']], popup=f"<b>{neighbor['tesis_adi']}</b><br>{neighbor.get('adres', '')}", tooltip=neighbor['tesis_adi'], icon=folium.Icon(color='blue', icon='industry', prefix='fa')).add_to(m)
                folium_static(m, height=500)
            except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")
        else:
            st.info("Rapor, harita çizimi için yeterli koordinat bilgisi içermiyor.")

        st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
        st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])).rename(columns={"adres": "Adres"}))
        st.markdown(f"**Kaynak Link:** [{report.get('kaynak_url')}]({report.get('kaynak_url')})")
else:
    st.info("Başlamak için lütfen kenar çubuğundaki butona tıklayarak analiz sürecini başlatın.")
