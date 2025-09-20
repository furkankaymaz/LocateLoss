# ==============================================================================
#      NİHAİ KOD (v20.0): Stabil Veritabanı ve Bütünleşik Analiz
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
    return st.connection("reports_db_v3", type="sql", url="sqlite:///reports_db_v3.db")
conn = init_connection()

# GÜNCELLEME: Veritabanı şeması son ve doğru haliyle burada tanımlanmıştır.
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
    prompt = f"""
    Sen, Türkiye odaklı çalışan, elit seviye bir sigorta ve risk istihbarat analistisin. Görevinin merkezinde doğruluk, detay ve kaynak gösterme vardır.
    ANA GÖREVİN: Web'i (haber ajansları, yerel basın) ve X'i (Twitter) aktif olarak tarayarak Türkiye'de son 10 gün içinde meydana gelmiş, sigortacılık açısından en önemli **en fazla 10 adet** endüstriyel veya enerji tesisi hasar olayını bul.
    KRİTİK TALİMATLAR:
    1.  **TEKİLLEŞTİRME ZORUNLUDUR:** Aynı olayı farklı kaynaklarda görsen bile, bunu tek bir olay olarak raporla ve tüm bilgileri o olay altında birleştir.
    2.  **DERİNLEMESİNE BİLGİ TOPLA:** Sadece başlıkları değil, haber metinlerinin ve X paylaşımlarının içeriğini OKU.
    3.  **KAYNAK GÖSTERME ZORUNLUDUR:** Özellikle tesis adı ve hasar tahmini gibi kritik bilgiler için kaynağını belirt.
    ÇIKTI FORMATI: Bulgularını, her bir olay için aşağıdaki anahtarlara sahip bir JSON nesnesi içeren bir JSON dizisi olarak döndür.
    JSON NESNE YAPISI: "event_key", "tesis_adi", "tesis_adi_kaynak", "sehir_ilce", "olay_tarihi", "olay_ozeti", "hasar_tahmini", "guncel_durum", "komsu_tesisler_metin", "latitude", "longitude", "kaynak_urller".
    """
    try:
        response = _client.chat.completions.create(model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}], max_tokens=8192, temperature=0.1)
        content = response.choices[0].message.content
        match = re.search(r'\[.*\]', content, re.DOTALL)
        return json.loads(match.group(0)) if match else []
    except Exception as e:
        st.error(f"Ana Analiz Motorunda Hata: {e}"); return []

@st.cache_data(ttl=86400)
def find_neighboring_facilities(api_key, lat, lon, radius=300):
    if not api_key or not lat or not lon: return []
    try:
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={float(lat)},{float(lon)}&radius={radius}&type=establishment&keyword=fabrika|depo|sanayi|tesis|lojistik|antrepo&key={api_key}"
        response = requests.get(url)
        results = response.json().get('results', [])
        return [{"tesis_adi": p.get('name'), "tip": ", ".join(p.get('types', [])), "konum": p.get('vicinity')} for p in results[:5]]
    except (requests.exceptions.RequestException, ValueError, TypeError) as e:
        st.warning(f"Google Places API hatası: {e}"); return []

# ------------------------------------------------------------------------------
# 3. GÜVENLİ VERİTABANI İŞLEMLERİ
# ------------------------------------------------------------------------------
# GÜNCELLEME: Bu fonksiyonlar tek ve doğru tablo şemasına göre çalışır.
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
            report_data = json.loads(row['report_json'])
            report_data['event_key'] = row['event_key']
            report_data['created_date'] = row['created_date']
            reports.append(report_data)
        except json.JSONDecodeError: continue
    return reports

# ------------------------------------------------------------------------------
# 4. ARAYÜZ VE ANA İŞLEM AKIŞI
# ------------------------------------------------------------------------------
st.sidebar.header("Otomatik Tarama")
run_auto_search = st.sidebar.button("Son Olayları Bul ve Analiz Et", type="primary", use_container_width=True)
st.sidebar.caption("Son 10 güne ait olayları tarar, tekilleştirir, zenginleştirir ve onayınıza sunar.")

tab1, tab2 = st.tabs(["🆕 Onay Bekleyen Yeni Raporlar", "🗃️ Kayıtlı Raporlar Veritabanı"])

if run_auto_search:
    if not client:
        st.error("Lütfen Grok API anahtarını Streamlit Secrets'a ekleyin."); st.stop()
    
    st.session_state.draft_reports = []
    with st.spinner("Ana Analiz Motoru çalıştırılıyor... Web ve X kaynakları taranıyor..."):
        ai_reports = get_latest_events_from_ai(client)

    if not ai_reports:
        st.warning("Analiz motoru yeni bir olay raporu üretemedi.")
    else:
        new_events_found = 0
        for report in ai_reports:
            if not check_event_exists(report.get('event_key', '')):
                report['komsu_tesisler_harita'] = find_neighboring_facilities(google_api_key, report.get('latitude'), report.get('longitude'))
                st.session_state.draft_reports.append(report)
                new_events_found += 1
        
        if new_events_found > 0:
            st.success(f"Analiz tamamlandı. Veritabanında bulunmayan {new_events_found} adet yeni olay raporu onaya sunuldu.")
        else:
            st.info("Tüm bulunan olaylar daha önce veritabanına kaydedilmiş. Onaylanacak yeni bir rapor yok.")
            st.balloons()
    st.rerun()

with tab1:
    if not st.session_state.draft_reports:
        st.info("Henüz onay bekleyen yeni bir rapor bulunmamaktadır. Lütfen yeni bir tarama başlatın.")
    else:
        st.info(f"Aşağıda onayınızı bekleyen {len(st.session_state.draft_reports)} adet yeni rapor bulunmaktadır.")
        for report in st.session_state.draft_reports:
            event_key = report.get('event_key', str(report))
            st.markdown("---")
            st.subheader(f"{report.get('tesis_adi', 'İsimsiz Tesis')} - {report.get('sehir_ilce', 'Konum Yok')}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Özet:** {report.get('olay_ozeti', 'N/A')}")
                st.caption(f"Tesis Adı Kaynağı: {report.get('tesis_adi_kaynak', 'N/A')}")
            with col2:
                st.info(f"**Güncel Durum:** {report.get('guncel_durum', 'N/A')}")
                st.warning(f"**Hasar Tahmini:** {report.get('hasar_tahmini', 'N/A')}")
            
            if st.button("✔️ Onayla ve Kaydet", key=event_key, type="primary"):
                save_report_to_db(event_key, report)
                st.success(f"'{event_key}' başarıyla veritabanına kaydedildi!")
                st.session_state.draft_reports = [r for r in st.session_state.draft_reports if r.get('event_key') != event_key]
                st.rerun()

            with st.expander("Harita, Komşu Tesisler ve Kaynakları Görüntüle"):
                lat, lon = report.get('latitude'), report.get('longitude')
                if lat and lon:
                    try:
                        m = folium.Map(location=[float(lat), float(lon)], zoom_start=15, tiles="CartoDB positron")
                        folium.Marker([float(lat), float(lon)], popup=f"<b>{report.get('tesis_adi')}</b>", icon=folium.Icon(color='red', icon='fire')).add_to(m)
                        folium_static(m, height=300)
                    except (ValueError, TypeError): st.warning("Geçersiz koordinat formatı, harita çizilemiyor.")

                st.markdown("##### Komşu Tesis Analizi (Haber Metinlerinden)")
                st.write(report.get('komsu_tesisler_metin', 'Metinlerde komşu tesislere dair bir bilgi bulunamadı.'))
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
                 st.json(report, expanded=False)
