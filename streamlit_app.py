# ==============================================================================
#      NİHAİ KOD (v17.0): Son Cila - "Ultra Detay" ve Şeffaf Arayüz
# ==============================================================================
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import folium_static
from openai import OpenAI
import json
import re
import requests
from datetime import datetime
from sqlalchemy import text

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE BAĞLANTILAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Endüstriyel Hasar İstihbaratı")
st.title("🛰️ Akıllı Endüstriyel Hasar İstihbarat Platformu")

# --- API ve Veritabanı Bağlantıları ---
grok_api_key = st.secrets.get("GROK_API_KEY")
google_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY")
client = OpenAI(api_key=grok_api_key, base_url="https://api.x.ai/v1") if grok_api_key else None

@st.cache_resource
def init_connection():
    return st.connection("reports_db_v2", type="sql", url="sqlite:///reports_db_v2.db")
conn = init_connection()

def create_tables_if_not_exist():
    with conn.session as s:
        s.execute(text('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, event_key TEXT UNIQUE, report_json TEXT, created_date TEXT);'))
        s.commit()
create_tables_if_not_exist()

if 'draft_reports' not in st.session_state:
    st.session_state.draft_reports = []

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_latest_events_from_ai(_client):
    # GÜNCELLEME: Bu "MASTER PROMPT", AI'dan çok daha granüler ve detaylı bilgi talep eder.
    prompt = f"""
    Sen, Türkiye odaklı çalışan, elit seviye bir sigorta ve risk istihbarat analistisin. Görevinin merkezinde doğruluk, kanıt ve derinlemesine detay vardır. Yüzeysel özetler kabul edilemez.

    ANA GÖREVİN: Web'i (haber ajansları) ve X'i (Twitter) aktif olarak tarayarak Türkiye'de son 10 gün içinde meydana gelmiş, sigortacılık açısından en önemli **en fazla 5 adet** endüstriyel veya enerji tesisi hasar olayını bul.

    KRİTİK TALİMATLAR:
    1.  **KANIT ZORUNLUDUR:** Her bilgi parçası için metinlerden kanıt bul. "Tesis adı ABC Kimya'dır çünkü DHA haberinde böyle belirtilmiştir" gibi düşün.
    2.  **DERİNLEMESİNE DETAY:** Sadece olayı değil, nedenini, fiziksel boyutunu ve yapılan müdahaleyi de araştır.
    3.  **TEKİLLEŞTİR VE BİRLEŞTİR:** Farklı kaynaklardaki aynı olayı tek bir zengin rapor altında birleştir.

    ÇIKTI FORMATI: Bulgularını, her bir olay için aşağıdaki detaylı anahtarlara sahip bir JSON nesnesi içeren bir JSON dizisi olarak döndür.
    
    JSON NESNE YAPISI:
    - "event_key": Olayı benzersiz kılan anahtar (Örn: "Gebze_Kimya_Yangini_2025_09_20").
    - "tesis_adi": Yüksek doğrulukla tespit edilmiş ticari unvan.
    - "tesis_adi_kaynak": Tesis adını hangi kaynaklara (X, haber ajansı vb.) dayanarak bulduğunun açıklaması.
    - "sehir_ilce": Olayın yaşandığı yer.
    - "olay_tarihi": Olayın tarihi (YYYY-AA-GG formatında).
    - "hasarin_nedeni": Olayın tahmini nedeni (Örn: "Elektrik panosundaki kısa devre", "Kimyasal reaksiyon").
    - "hasarin_fiziksel_boyutu": Hasarın fiziksel etkisi (Örn: "Fabrikanın 5000 metrekarelik depo bölümü tamamen yandı.", "Üretim bandı-2 hasar gördü.").
    - "yapilan_mudahale": Resmi kurumların müdahalesi (Örn: "Olay yerine 15 itfaiye aracı sevk edildi, soğutma çalışmaları 8 saat sürdü.").
    - "hasar_tahmini_parasal": Parasal hasar bilgisi ve kaynağı (Örn: "İlk belirlemelere göre 25 Milyon TL. Kaynak: Şirket sahibinin açıklaması.").
    - "guncel_durum": Üretim durdu mu, soruşturma başladı mı gibi en son bilgiler.
    - "komsu_tesisler_metin": Haber metinlerinde, olayın komşu tesislere olan etkisinden bahsediliyor mu?
    - "latitude": Olay yerinin enlemi (Sadece sayı, tahmin de olabilir).
    - "longitude": Olay yerinin boylamı (Sadece sayı, tahmin de olabilir).
    - "analiz_guveni": Bu rapordaki bilgilerin genel güvenilirliğine 1-5 arası verdiğin puan.
    - "analiz_sureci_ozeti": Bu raporu hazırlarken hangi adımları attığının kısa özeti (Örn: "3 haber ajansı tarandı, firma adı teyidi için X'teki paylaşımlar incelendi.").
    - "kaynak_urller": Kullandığın tüm haber ve X linklerinin listesi (dizi).
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return []

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=500):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:10]]
    except Exception as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. VERİTABANI İŞLEMLERİ (Değişiklik yok)
# ------------------------------------------------------------------------------
def check_event_exists(event_key):
    df = conn.query("SELECT id FROM reports WHERE event_key = :key;", params={"key": event_key})
    return not df.empty

def save_report_to_db(event_key, report_json):
    with conn.session as s:
        s.execute(text("INSERT INTO reports (event_key, report_json, created_date) VALUES (:key, :json, :date);"),
                  params={"key": event_key, "json": json.dumps(report_json, ensure_ascii=False), "date": datetime.now().isoformat()})
        s.commit()

def get_all_reports_from_db():
    df = conn.query("SELECT event_key, report_json, created_date FROM reports ORDER BY created_date DESC;", ttl=300)
    reports = []
    for index, row in df.iterrows():
        try:
            report_data = json.loads(row['report_json']); report_data['event_key'] = row['event_key']; report_data['created_date'] = row['created_date']
            reports.append(report_data)
        except json.JSONDecodeError: continue
    return reports

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Otomatik Tarama")
run_auto_search = st.sidebar.button("Son Olayları Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("En son ve en önemli olayları tarar, detaylandırır, zenginleştirir ve onayınıza sunar.")

tab1, tab2 = st.tabs(["🆕 Onay Bekleyen Yeni Raporlar", "🗃️ Kayıtlı Raporlar Veritabanı"])

if run_auto_search:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()
    
    st.session_state.draft_reports = []
    with st.status("Akıllı Analiz süreci yürütülüyor...", expanded=True) as status:
        status.write("Aşama 1: Ana Analiz Motoru çalıştırılıyor, web ve X kaynakları taranıyor...")
        ai_reports = get_latest_events_from_ai(client)

        if not ai_reports:
            status.update(label="Analiz tamamlandı. Yeni bir olay bulunamadı.", state="complete", expanded=False)
            st.warning("Analiz motoru yeni bir olay raporu üretemedi.")
        else:
            new_events_found = 0
            for i, report in enumerate(ai_reports):
                event_key = report.get('event_key', f'olay_{i}')
                report['event_key'] = event_key # event_key yoksa ata
                
                status.write(f"Aşama 2: '{event_key}' veritabanında kontrol ediliyor...")
                if not check_event_exists(event_key):
                    status.write(f"Aşama 3: '{event_key}' için Google Maps'ten komşu tesis verileri çekiliyor...")
                    report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
                    st.session_state.draft_reports.append(report)
                    new_events_found += 1
            
            if new_events_found > 0:
                status.update(label=f"Analiz tamamlandı! {new_events_found} yeni rapor onaya hazır.", state="complete", expanded=False)
            else:
                status.update(label="Analiz tamamlandı. Tüm olaylar daha önce kaydedilmiş.", state="complete", expanded=False)
                st.balloons()
    st.rerun()

with tab1:
    if not st.session_state.draft_reports:
        st.info("Henüz onay bekleyen yeni bir rapor bulunmamaktadır. Lütfen yeni bir tarama başlatın.")
    else:
        for report in st.session_state.draft_reports:
            event_key = report.get('event_key')
            st.markdown("---")
            st.subheader(f"{report.get('tesis_adi', 'İsimsiz Tesis')} - {report.get('sehir_ilce', 'Konum Yok')}")
            
            st.markdown(f" Güven Skoru: **{report.get('analiz_guveni', 'N/A')}/5** | *AI Süreç Özeti: {report.get('analiz_sureci_ozeti', 'N/A')}*")
            st.caption(f"Tesis Adı Kaynağı: {report.get('tesis_adi_kaynak', 'N/A')}")
            
            col1, col2, col3 = st.columns(3)
            with col1: st.info(f"**Hasarın Nedeni:** {report.get('hasarin_nedeni', 'N/A')}")
            with col2: st.success(f"**Yapılan Müdahale:** {report.get('yapilan_mudahale', 'N/A')}")
            with col3: st.error(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")

            st.warning(f"**Hasarın Fiziksel Boyutu:** {report.get('hasarin_fiziksel_boyutu', 'N/A')}")
            st.metric(label="Parasal Hasar Tahmini", value=report.get('hasar_tahmini_parasal', 'Tespit Edilemedi'))
            
            if st.button("✔️ Onayla ve Kaydet", key=event_key, type="primary"):
                save_report_to_db(event_key, report)
                st.success(f"Rapor veritabanına kaydedildi! 'Kayıtlı Raporlar' sekmesinden görüntüleyebilirsiniz.")
                st.session_state.draft_reports = [r for r in st.session_state.draft_reports if r.get('event_key') != event_key]
                st.rerun()

            with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle"):
                #... (Harita ve diğer detaylar)
                lat, lon = report.get('latitude'), report.get('longitude')
                if lat and lon:
                    try:
                        m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                        folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                        folium_static(m, height=300)
                    except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı.")
                st.markdown("##### Komşu Tesisler (Google Harita Verisi)")
                st.table(pd.DataFrame(report.get('komsu_tesisler_harita', [])))
                st.markdown("##### Kaynak Linkler")
                for link in report.get('kaynak_urller', []): st.markdown(f"- {link}")

with tab2:
    st.header("🗃️ Kayıtlı Raporlar Veritabanı")
    if st.button("Kayıtlı Raporları Yenile"): st.rerun()
    
    all_reports = get_all_reports_from_db()
    if not all_reports:
        st.info("Veritabanında henüz kaydedilmiş bir rapor bulunmamaktadır.")
    else:
        st.success(f"Veritabanında toplam {len(all_reports)} adet rapor bulundu.")
        for report in all_reports:
            tarih = pd.to_datetime(report['created_date']).strftime('%d %b %Y, %H:%M')
            with st.expander(f"**{report.get('tesis_adi', 'İsimsiz Tesis')}** - {report.get('sehir_ilce', 'Konum Yok')} (Kayıt: {tarih})"):
                 st.json(report, expanded=True)
