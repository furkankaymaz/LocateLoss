# ==============================================================================
#  NİHAİ KOD (v59.0): Odaklanmış Uzman Ajan
#  AMAÇ: Tek ve en güçlü hedefle çalışan, güncel ve tutarlı sonuçlar üreten,
#  API kullanımı optimize edilmiş nihai bir ajan sunmak.
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
st.set_page_config(layout="wide", page_title="Uzman İstihbarat Ajanı")
st.title("🛰️ Odaklanmış Uzman İstihbarat Ajanı")
st.info("Bu ajan, Türkiye'deki son 45 günlük endüstriyel hasarları bulmak üzere özel olarak eğitilmiştir. En güncel ve en önemli olayları tespit etmek için otonom olarak araştırma yapar.")

# --- API Anahtarları
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY")
GROK_API_KEY = st.secrets.get("GROK_API_KEY")

# ------------------------------------------------------------------------------
# 2. OTONOM AJANIN KURULUMU VE ÇALIŞTIRILMASI
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600) # Aynı sorgu için 1 saat boyunca sonucu hafızada tut
def run_expert_agent():
    """
    Önceden tanımlanmış, odaklanmış bir hedef doğrultusunda otonom bir ajanı çalıştırır.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    # Araç, optimize edilmiş sabit bir derinlikle yapılandırıldı.
    tools = [TavilySearchResults(max_results=10)]

    llm = ChatOpenAI(
        model_name="grok-4-fast-reasoning",
        openai_api_key=GROK_API_KEY,
        openai_api_base="https://api.x.ai/v1",
        temperature=0,
        streaming=False
    )

    # GÜNCELLEME: Prompt, ajanı en güncel olaylara ve X'e odaklanmaya zorlar.
    # Tarih aralığı (8 Ağustos 2025 - 22 Eylül 2025) statik olarak belirtilmiştir.
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki güncel endüstriyel hasarlar konusunda uzmanlaşmış, sıfır halüsinasyon ilkesiyle çalışan bir istihbarat analistisin.

        ANA GÖREVİN: 8 Ağustos 2025 - 22 Eylül 2025 tarihleri arasında Türkiye'de gerçekleşmiş, sigortacılık açısından önemli tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden) bulmak.

        KRİTİK TALİMATLAR:
        1.  **GÜNCELLİK:** Sadece belirtilen tarih aralığındaki olaylara odaklan. Daha eski olayları raporlama.
        2.  **TESİS ADI TESPİTİ:** Şirket adını bulmak senin birincil görevin. Özellikle X (Twitter) gibi anlık kaynaklarda geçen isimleri ve yerel basındaki ipuçlarını değerlendir. Sadece hiçbir ipucu yoksa 'Belirtilmemiş' yaz.
        3.  **KAPSAM:** Hiçbir önemli haberi atlama. Büyük olayların yanı sıra, yerel basına yansımış daha küçük ama anlamlı hasarları da bulmaya çalış.
        4.  **RAPOR FORMATI:** Bulduğun her bir olayı, aşağıdaki Markdown tablo yapısına harfiyen uyarak raporla. Tüm sütunları kanıtlara dayanarak doldur.

        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Etkilenen Çevre Tesisleri (Detaylı Etki) | Referans URL |
        |------|-------|------------|-------------------|----------------|-------------------------------------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    # Ajanın ana hedefi artık statik ve optimize edilmiş.
    user_objective = "Türkiye'de son 45 gün içinde (8 Ağustos 2025 - 22 Eylül 2025) gerçekleşmiş, basına yansımış (X dahil) tüm endüstriyel hasarları bul ve raporla."

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

st.subheader("Görev: Son 45 Günlük Endüstriyel Hasar Taraması")
st.write("Aşağıdaki butona bastığınızda, ajan **8 Ağustos 2025 - 22 Eylül 2025** tarihleri arasındaki en güncel ve önemli endüstriyel hasarları bulmak için otonom bir araştırma başlatacaktır.")

if st.button("Güncel Hasar Raporunu Oluştur", type="primary", use_container_width=True):
    with st.spinner("Uzman Ajan çalışıyor... En güncel olayları bulmak için X ve diğer güvenilir kaynaklar taranıyor. Bu işlem birkaç dakika sürebilir."):
        final_report, thought_process = run_expert_agent()
        st.session_state.final_report = final_report
        st.session_state.thought_process = thought_process

# --- SONUÇLARI GÖSTER ---
if 'final_report' in st.session_state and st.session_state.final_report:
    st.markdown("---")
    st.subheader("Ajanın Nihai Raporu")
    st.markdown(st.session_state.final_report)

    with st.expander("Ajanın Düşünce Sürecini Göster (Şeffaflık Raporu)"):
        st.text_area("Ajanın Adım Adım Düşünceleri ve Yaptığı Aramalar:", 
                     st.session_state.get('thought_process', 'Düşünce süreci kaydedilemedi.'), 
                     height=400)
