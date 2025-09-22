# ==============================================================================
#  NİHAİ KOD (v60.0): Rafine Edilmiş Otonom Ajan
#  FELSEFE: Ajan'a katı kurallar yerine, bir "Görev" ve "Yol Gösterici İlkeler"
#  vererek, otonom ve yaratıcı araştırma yeteneğini en üst düzeye çıkarmak.
# ==============================================================================
import streamlit as st
import os
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.prompts import ChatPromptTemplate
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta

# ------------------------------------------------------------------------------
# 1. TEMEL AYARLAR
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Rafine Edilmiş Otonom Ajan")
st.title("🛰️ Rafine Edilmiş Otonom İstihbarat Ajanı")
st.info("Bu ajan, verilen görev tanımı çerçevesinde, en güncel ve önemli endüstriyel hasarları bulmak için otonom olarak en iyi araştırma stratejisini belirler ve uygular.")

# --- API Anahtarları
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
GROK_API_KEY = st.secrets.get("GROK_API_KEY")

# ------------------------------------------------------------------------------
# 2. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Aynı görev için sonucu 1 saat hafızada tut
def run_refined_agent(user_objective):
    """
    Rafine edilmiş bir prompt ile otonom ajanı çalıştırır.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    # Araç, optimize edilmiş sabit bir derinlikle yapılandırıldı.
    tools = [TavilySearchResults(max_results=7)]

    llm = ChatOpenAI(
        model_name="grok-4-fast-reasoning",
        openai_api_key=GROK_API_KEY,
        openai_api_base="https://api.x.ai/v1",
        temperature=0,
        streaming=False
    )

    # GÜNCELLEME: Prompt, katı kurallar yerine bir görev tanımı ve yol gösterici ilkeler içerir.
    # Bu, ajanın esnek ve akıllı düşünmesini sağlar.
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki güncel endüstriyel hasarlar konusunda uzman, sıfır halüsinasyon ilkesiyle çalışan bir OSINT analistisin.

        ANA GÖREVİN (MİSYON): Sana verilen zaman aralığı içinde Türkiye'de gerçekleşmiş, sigortacılık açısından önemli tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden vb.) bulmak ve raporlamak.

        YOL GÖSTERİCİ İLKELERİN:
        1.  **Kapsamlı Ol:** Sadece bir iki olay bulup durma. Görevin, mümkün olan en fazla sayıda anlamlı olayı ortaya çıkarmak. Bunun için farklı anahtar kelimelerle birden çok arama yapmaktan çekinme.
        2.  **Tesis Adı Önceliği:** Raporunun en değerli kısmı tesis adıdır. Teyit edilmiş bir ticari unvan bulmak için tüm kanıtları dikkatle incele. Sadece hiçbir ipucu bulamazsan 'Belirtilmemiş' olarak raporla.
        3.  **Güncelliği Koru:** Sadece sana belirtilen tarih aralığına odaklan. Bu aralığın dışındaki olaylar ilgisizdir.
        4.  **Kanıta Daya:** Her bir bilgiyi, arama sonuçlarından bulduğun bir kaynağa dayandır.
        5.  **Standartlara Uy:** Nihai çıktın, SADECE istenen formatta bir Markdown tablosu olmalıdır.

        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
        |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

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
# Tarih aralığını dinamik olarak hesapla
today = datetime.now()
start_date = today - timedelta(days=45)
date_range_str = f"{start_date.strftime('%d %B %Y')} - {today.strftime('%d %B %Y')}"

st.subheader(f"Görev: {date_range_str} Arası Endüstriyel Hasar Taraması")

# Ajanın ana hedefi artık sabit, net ve optimize edilmiş.
user_objective = f"Türkiye'de {date_range_str} tarihleri arasında gerçekleşmiş, basına yansımış (X dahil), sigortacılık açısından önemli tüm endüstriyel hasarları bul ve raporla."

st.write("Aşağıdaki butona bastığınızda, ajan belirtilen tarihler arasındaki en güncel ve önemli endüstriyel hasarları bulmak için otonom bir araştırma başlatacaktır.")

if st.button("Güncel Hasar Raporunu Oluştur", type="primary", use_container_width=True):
    with st.spinner("Uzman Ajan çalışıyor... En iyi stratejiyi belirleyip, güncel olayları bulmak için kaynakları tarıyor. Bu işlem birkaç dakika sürebilir."):
        final_report, thought_process = run_refined_agent(user_objective)
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Ajanın Nihai Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Düşünce Sürecini Göster (Şeffaf Rapor)"):
        st.text_area("Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar:", 
                     st.session_state.get('thought_process', 'Düşünce süreci kaydedilemedi.'), 
                     height=400)
