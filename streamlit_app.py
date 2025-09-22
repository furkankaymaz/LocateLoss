# ==============================================================================
#  NİHAİ KOD (v58.0): Gelişmiş İstihbarat Ajanı
#  YENİLİKLER:
#  - Zenginleştirilmiş ve standart rapor tablosu (daha fazla detay).
#  - Tesis adı bulmak için daha agresif prompt.
#  - Kullanıcının maliyet/kalite dengesini ayarlayabilmesi için arayüze eklenen kontrol.
# ==============================================================================
import streamlit as st
import os
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
import io
from contextlib import redirect_stdout

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Gelişmiş İstihbarat Ajanı")
st.title("🛰️ Gelişmiş Otonom İstihbarat Ajanı")
st.info("Bu ajan, hedefinizi otonom olarak araştırır ve bulduğu kanıtları sentezleyerek detaylı bir istihbarat raporu oluşturur.")

# --- API Anahtarları
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
GROK_API_KEY = st.secrets.get("GROK_API_KEY")

# ------------------------------------------------------------------------------
# 2. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def run_autonomous_agent(user_objective, max_results):
    """
    Verilen hedef doğrultusunda, LangChain ile inşa edilmiş otonom bir ajanı çalıştırır.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    # GÜNCELLEME: Araç, kullanıcı tarafından belirlenen max_results ile yapılandırıldı.
    tools = [TavilySearchResults(max_results=max_results)]

    llm = ChatOpenAI(
        model_name="grok-4-fast-reasoning",
        openai_api_key=GROK_API_KEY,
        openai_api_base="https://api.x.ai/v1",
        temperature=0,
        streaming=False
    )

    # GÜNCELLEME: Prompt, daha fazla detay ve daha agresif isim tespiti için tamamen yenilendi.
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki endüstriyel hasarlar konusunda uzman, sıfır halüsinasyon ilkesiyle çalışan bir istihbarat analistisin.
        
        BİRİNCİL GÖREVİN: Tesisin tam ticari unvanını bulmaktır. Metinlerdeki en ufak ipuçlarını ('ABC Lojistik'e ait...', 'XYZ A.Ş. fabrikası' gibi) değerlendir. Sadece hiçbir ipucu yoksa 'Belirtilmemiş' yaz.

        İKİNCİL GÖREVİN: Bulduğun her bir olayı, aşağıdaki Markdown tablo yapısına harfiyen uyarak raporla. Her bir sütunu, arama sonuçlarındaki kanıtlara dayanarak doldur. Bilgi yoksa 'Belirtilmemiş' yaz.

        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
        |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    thought_process_stream = io.StringIO()
    try:
        with redirect_stdout(thought_process_stream):
            result = agent_executor.invoke({"input": user_objective})
        
        thought_process = thought_process_stream.getvalue()
        final_output = result.get("output", "Bir çıktı üretilemedi.")
        return final_output, thought_process
        
    except Exception as e:
        st.error(f"Ajan çalışırken bir hata oluştu: {e}")
        return None, thought_process_stream.getvalue()

# ------------------------------------------------------------------------------
# 3. STREAMLIT ARAYÜZÜ
# ------------------------------------------------------------------------------

st.subheader("1. Adım: Ajanın Görevini ve Parametrelerini Belirleyin")

default_objective = "Türkiye'de son 45 günde (bugün 22 Eylül 2025) gerçekleşmiş, basına yansımış tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden, rafineri) bul ve raporla."
user_objective = st.text_area(
    "Ajanın Araştırmasını İstediğiniz Ana Hedef:",
    default_objective,
    height=100
)

# YENİ: Maliyet/Kalite kontrolü için ayar
max_results = st.slider(
    "Araştırma Derinliği (Sonuç Sayısı):",
    min_value=5,
    max_value=25,
    value=10, # Varsayılan değer
    help="Ajanın her bir arama adımında toplayacağı maksimum kanıt sayısı. Yüksek değerler daha kapsamlı ama daha yavaş sonuçlar üretebilir."
)

st.subheader("2. Adım: Ajanı Başlatın")
if st.button("Otonom Araştırmayı Başlat", type="primary", use_container_width=True):
    with st.spinner("Otonom Ajan çalışıyor... Bu işlem, araştırma derinliğine göre birkaç dakika sürebilir."):
        final_report, thought_process = run_autonomous_agent(user_objective, max_results)
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Ajanın Nihai Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Düşünce Sürecini Göster (Şeffaflık Raporu)"):
        st.text_area("Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar:", 
                     st.session_state.get('thought_process', ''), 
                     height=400)
