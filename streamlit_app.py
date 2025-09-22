# ==============================================================================
#  NİHAİ KOD (v52.0): Çoklu-Sorgu İstihbarat Ajanı
#  AMAÇ: Kapsamı genişletmek için otomatik olarak çok sayıda hedefli sorgu
#  oluşturup, sonuçları birleştirerek analiz etmek.
# ==============================================================================
import streamlit as st
import requests
from openai import OpenAI
import os
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR VE YAPILANDIRMA
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Çoklu-Sorgu İstihbarat Ajanı")
st.title("🛰️ Çoklu-Sorgu İstihbarat Ajanı")
st.info("Bu ajan, kapsamı en üst düzeye çıkarmak için Türkiye'nin sanayi şehirleri ve farklı risk tipleri bazında otomatik olarak çok sayıda hedefli arama yapar.")

# --- API Anahtarları
GROK_API_KEY = st.secrets.get("GROK_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1") if GROK_API_KEY else None

# --- Arama Matrisi için Sabitler
INDUSTRIAL_CITIES = ["İstanbul", "Kocaeli", "Bursa", "İzmir", "Ankara", "Gaziantep", "Tekirdağ", "Konya", "Kayseri", "Adana", "Manisa", "Denizli"]
RISK_KEYWORDS = ["yangın", "patlama", "kaza", "sızıntı", "göçük"]

# ------------------------------------------------------------------------------
# 2. ÇEKİRDEK FONKSİYONLAR
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def run_multi_query_search(date_option):
    """
    Önceden tanımlanmış şehir ve risk listelerine göre çok sayıda hedefli sorgu oluşturur
    ve Tavily API ile aratarak birleşik bir kanıt dosyası döndürür.
    """
    if not TAVILY_API_KEY:
        st.error("Tavily API anahtarı bulunamadı.")
        return None
    
    # 1. Otomatik Sorgu Üretimi
    queries = []
    base_keywords = ["fabrika", "sanayi", "OSB", "depo", "tesis", "liman"]
    for city in INDUSTRIAL_CITIES:
        for risk in RISK_KEYWORDS:
            for keyword in base_keywords:
                 queries.append(f'"{city}" "{keyword}" "{risk}" son {date_option.lower()}')

    # 2. Katmanlı Arama
    st.info(f"Kapsamlı bir analiz için toplam {len(queries)} adet hedefli sorgu oluşturuldu. Bu işlem biraz zaman alabilir.")
    progress_bar = st.progress(0, text="Hedefli aramalar başlatılıyor...")
    
    all_results = {} # URL'leri key olarak kullanarak duplikeleri engelle
    for i, query in enumerate(queries):
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={ "api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 3 }
            )
            response.raise_for_status()
            results = response.json().get('results', [])
            for result in results:
                if result['url'] not in all_results:
                    all_results[result['url']] = result
            
            # Her 10 sorguda bir API limitlerini aşmamak için kısa bir bekleme
            if (i + 1) % 10 == 0:
                time.sleep(1)

        except Exception as e:
            # Bir sorgu hata verirse devam et
            st.warning(f"'{query}' sorgusu işlenirken bir hata oluştu: {e}")
            continue
        finally:
            progress_bar.progress((i + 1) / len(queries), text=f"Sorgu {i+1}/{len(queries)} tamamlandı: {query}")

    # 3. Birleşik Kanıt Dosyası Oluşturma
    context = "BİRLEŞİK KANIT DOSYASI:\n\n"
    for i, result in enumerate(all_results.values()):
        context += f"Kaynak {i+1}:\nBaşlık: {result['title']}\nURL: {result['url']}\nÖzet: {result['content']}\n\n"
    
    return context

@st.cache_data(ttl=3600, show_spinner="Grok AI, toplanan kapsamlı kanıtları analiz edip nihai raporu oluşturuyor...")
def generate_final_report_from_comprehensive_data(_client, user_query, evidence_context):
    """
    Çok sayıda aramadan toplanan birleşik kanıt dosyasını analiz eder.
    """
    if not _client:
        st.error("Grok API anahtarı bulunamadı.")
        return None
        
    prompt = f"""
    Sen, kanıta dayalı çalışan bir Baş İstihbarat Analistisin. Halüsinasyona sıfır toleransın var. Sadece sana sunulan BİRLEŞİK KANIT DOSYASI'ndaki bilgileri kullanacaksın.

    KULLANICININ ANA HEDEFİ: "{user_query}"

    SANA SUNULAN BİRLEŞİK KANIT DOSYASI (Onlarca farklı aramadan toplanan sonuçlar):
    ---
    {evidence_context}
    ---

    GÖREVİN:
    1. Yukarıdaki devasa kanıt dosyasını dikkatlice incele.
    2. Kullanıcının ana hedefini karşılayacak şekilde, bu kanıtlara dayanarak, bulduğun TÜM olayları içeren detaylı bir tablo formatında bir rapor oluştur.
    3. Olayları birleştir ve duplicate (aynı olayın farklı haberleri) olanları tek bir satırda özetle. Şirket adını bulmaya özellikle odaklan.
    4. Bir bilgi kanıtlarda mevcut değilse, o hücreye "Kanıtlarda Belirtilmemiş" yaz. ASLA TAHMİN YÜRÜTME.
    5. Referans URL sütununa, bilgiyi aldığın en güvenilir kaynağın URL'ini ekle.

    İSTENEN ÇIKTI FORMATI:
    | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
    |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}],
            max_tokens=4096, temperature=0.0, timeout=300.0
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Grok AI ile rapor oluşturulurken hata oluştu: {e}")
        return None

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Arama Parametrelerini Seçin")
date_option = st.selectbox(
    "Hangi Zaman Aralığını Taramak İstersiniz?",
    ("45 gün", "3 ay", "6 ay", "1 yıl")
)
user_query_for_grok = f"Türkiye'de son {date_option} içinde gerçekleşmiş tüm önemli endüstriyel hasarları (fabrika, depo, OSB, liman, maden), firma adları, etkileri ve çevre tesisleri ile birlikte detaylı bir şekilde listele."

st.subheader("2. Adım: Ajanı Başlatın")
if st.button("Kapsamlı Araştırma Yap ve Rapor Oluştur", type="primary", use_container_width=True):
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını eklediğinizden emin olun.")
    else:
        st.session_state.final_report = None; st.session_state.evidence_context = None
        evidence = run_multi_query_search(date_option)
        if evidence and len(evidence) > 50: # Eğer hiç kanıt bulunamazsa Grok'u boşuna çağırma
            st.session_state.evidence_context = evidence
            final_report = generate_final_report_from_comprehensive_data(grok_client, user_query_for_grok, evidence)
            st.session_state.final_report = final_report
        else:
            st.warning("Yapılan kapsamlı arama sonucunda analiz edilecek yeterli kanıt bulunamadı.")

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Nihai İstihbarat Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Analiz Ettiği Ham Kanıtları Gör (Toplamda {} karakter)".format(len(st.session_state.get('evidence_context', '')))):
        st.text_area("Tavily'den Gelen Birleşik Kanıt Dosyası", st.session_state.get('evidence_context', ''), height=400)
