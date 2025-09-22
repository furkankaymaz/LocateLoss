# ==============================================================================
#  NİHAİ KOD (v53.0): AI Araştırma Stratejisti
#  AMAÇ: AI'nın kendisinin bir araştırma planı (sorgu listesi) oluşturması,
#  bu planı uygulayıp kanıt toplaması ve son olarak bu kanıtları sentezleyip
#  nihai bir rapor oluşturması.
# ==============================================================================
import streamlit as st
import requests
from openai import OpenAI
import json
import time

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="AI Araştırma Stratejisti")
st.title("🛰️ AI Destekli Oto-İstihbarat Ajanı")
st.info("Bu ajan, önce neyi nasıl araştıracağını AI ile planlar, ardından bu planı uygulayarak kanıt toplar ve son olarak topladığı kanıtları sentezleyerek bir rapor oluşturur.")

# --- API Anahtarları
GROK_API_KEY = st.secrets.get("GROK_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
grok_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1") if GROK_API_KEY else None

# ------------------------------------------------------------------------------
# 2. ÜÇ AŞAMALI AJAN FONKSİYONLARI
# ------------------------------------------------------------------------------

# 1. Adım: AI Araştırma Planlayıcısı
@st.cache_data(ttl=3600, show_spinner="AI, en iyi araştırma stratejisini planlıyor...")
def generate_search_queries_with_ai(_client, user_objective):
    """Verilen ana hedefe ulaşmak için en etkili arama sorgularının bir listesini AI ile oluşturur."""
    prompt = f"""
    Sen bir OSINT (Açık Kaynak İstihbarat) araştırma stratejistisin.
    Ana Hedef: "{user_objective}"
    Görevin: Bu hedefe ulaşmak için bir web arama motorunda (Tavily) kullanılacak, birbirinden farklı ve hedef odaklı 10 adet arama sorgusu oluşturmak.
    Sorguları oluştururken şu açılardan düşün:
    - Türkiye'nin ana sanayi şehirleri (Kocaeli, Bursa, İzmir vb.)
    - Farklı endüstriyel risk türleri (yangın, patlama, kimyasal sızıntı, maden göçüğü vb.)
    - Tesis türleri (fabrika, OSB, liman, depo vb.)
    - Genel ve kapsayıcı sorgular.
    
    Çıktı olarak SADECE python listesi formatında, her bir sorgu tırnak içinde olacak şekilde ver.
    Örnek Çıktı:
    ["Kocaeli Gebze OSB fabrika yangın", "Türkiye maden kazaları son 45 gün", "İzmir Aliağa rafineri haberleri"]
    """
    try:
        response = _client.chat.completions.create(
            model="grok-4-fast-reasoning", messages=[{"role": "user", "content": prompt}],
            max_tokens=1024, temperature=0.5
        )
        # AI'dan gelen string listesini gerçek bir Python listesine çevir
        query_list_str = response.choices[0].message.content
        return json.loads(query_list_str.replace("'", '"'))
    except Exception as e:
        st.error(f"AI strateji oluştururken hata: {e}")
        # Fallback olarak basit bir liste döndür
        return [user_objective]

# 2. Adım: Kanıt Toplayıcı
@st.cache_data(ttl=3600)
def gather_evidence_with_tavily(queries):
    """AI'nın oluşturduğu sorgu listesini kullanarak Tavily ile kanıt toplar."""
    if not TAVILY_API_KEY:
        st.error("Tavily API anahtarı bulunamadı."); return None
    
    progress_bar = st.progress(0, text="AI'nın oluşturduğu strateji uygulanıyor...")
    all_results = {} # Duplikeleri URL bazında engelle
    
    for i, query in enumerate(queries):
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 5}
            )
            response.raise_for_status()
            results = response.json().get('results', [])
            for result in results:
                if result.get('url') and result['url'] not in all_results:
                    all_results[result['url']] = result
            if (i + 1) % 5 == 0: time.sleep(1) # API rate limitlerini zorlamamak için bekle
        except Exception:
            continue # Bir sorgu hata verirse diğerleriyle devam et
        finally:
            progress_bar.progress((i + 1) / len(queries), text=f"Stratejik Sorgu {i+1}/{len(queries)}: {query}")

    context = "BİRLEŞİK KANIT DOSYASI:\n\n"
    for i, result in enumerate(all_results.values()):
        context += f"Kaynak {i+1}:\nBaşlık: {result['title']}\nURL: {result['url']}\nÖzet: {result['content']}\n\n"
    return context

# 3. Adım: Rapor Sentezleyici
@st.cache_data(ttl=3600, show_spinner="AI Analisti, toplanan tüm kanıtları sentezleyip nihai raporu oluşturuyor...")
def synthesize_report_with_grok(_client, user_objective, evidence_context):
    """Toplanan kanıtlardan nihai raporu oluşturur."""
    prompt = f"""
    Sen, kanıta dayalı çalışan bir Baş İstihbarat Analistisin. Halüsinasyona sıfır toleransın var. Sadece sana sunulan BİRLEŞİK KANIT DOSYASI'ndaki bilgileri kullan.

    KULLANICININ ANA HEDEFİ: "{user_objective}"
    SANA SUNULAN KANIT DOSYASI (AI Stratejisi ile toplanan sonuçlar):
    ---
    {evidence_context}
    ---
    GÖREVİN: Kanıt dosyasını analiz et ve kullanıcının hedefine uygun, bulduğun TÜM olayları içeren, duplikeleri birleştirilmiş tek bir Markdown tablosu oluştur.
    Eğer bir bilgi kanıtlarda yoksa "Belirtilmemiş" yaz. ASLA TAHMİN YÜRÜTME.

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
        st.error(f"Grok rapor oluştururken hata: {e}"); return None

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Ana Araştırma Hedefini Belirleyin")
user_objective = st.text_input(
    "Ajanın araştırmasını istediğiniz ana hedefi girin:",
    "Türkiye'de son 45 gün içinde gerçekleşmiş, sigortacılık açısından önemli tüm endüstriyel hasarların (fabrika, depo, OSB, maden) listesi."
)

st.subheader("2. Adım: Ajanı Başlatın")
if st.button("Araştırma Stratejisi Oluştur, Uygula ve Raporla", type="primary", use_container_width=True):
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını eklediğinizden emin olun.")
    else:
        # Tüm süreci başlat
        st.session_state.queries = generate_search_queries_with_ai(grok_client, user_objective)
        if st.session_state.queries:
            st.session_state.evidence = gather_evidence_with_tavily(st.session_state.queries)
            if st.session_state.evidence and len(st.session_state.evidence) > 50:
                st.session_state.final_report = synthesize_report_with_grok(grok_client, user_objective, st.session_state.evidence)

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Nihai İstihbarat Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Çalışma Detayları (Şeffaflık Raporu)"):
        st.write("**Adım 1: AI'nın Oluşturduğu Arama Stratejisi (Sorgu Listesi):**")
        st.json(st.session_state.get('queries', []))
        st.write("**Adım 2: Toplanan Ham Kanıtlar:**")
        st.text_area("Tavily'den Gelen Birleşik Kanıt Dosyası", st.session_state.get('evidence', ''), height=400)
