@st.cache_data(ttl=3600) # Aynı görev için sonucu 1 saat hafızada tut
def run_autonomous_agent(user_objective):
    """
    Verilen hedef doğrultusunda, LangChain ile inşa edilmiş otonom bir ajanı çalıştırır.
    Ajanın düşünce sürecini ve nihai çıktısını döndürür.
    """
    if not TAVILY_API_KEY or not GROK_API_KEY:
        st.error("Lütfen hem Grok hem de Tavily API anahtarlarını Streamlit Secrets'a ekleyin.")
        return None, None

    # 1. Adım: Ajanın Araçlarını Tanımla
    tools = [TavilySearchResults(max_results=10)]

    # 2. Adım: Ajanın Beynini Tanımla
    llm = ChatOpenAI(
        # DÜZELTME: Grok API dokümantasyonunda belirtilen, genel erişime açık ve en güncel model adı.
        model_name="llama3-70b-8192", 
        openai_api_key=GROK_API_KEY,
        openai_api_base="https://api.x.ai/v1",
        temperature=0,
        streaming=False
    )

    # 3. Adım: Ajanın Görev Tanımı
    prompt = ChatPromptTemplate.from_messages([
        ("system", """Sen, Türkiye'deki güncel endüstriyel hasarlar konusunda uzman, sıfır halüsinasyon ilkesiyle çalışan bir OSINT analistisin.

        ANA GÖREVİN (MİSYON): Sana verilen zaman aralığı içinde Türkiye'de gerçekleşmiş, sigortacılık açısından önemli tüm endüstriyel hasarları (fabrika, depo, OSB, liman, maden vb.) bulmak ve raporlamak.

        YOL GÖSTERİCİ İLKELERİN:
        1.  **Kapsamlı Ol:** Sadece bir iki olay bulup durma. Görevin, mümkün olan en fazla sayıda anlamlı olayı ortaya çıkarmak. Bunun için farklı anahtar kelimelerle birden çok arama yapmaktan çekinme.
        2.  **Tesis Adı Önceliği:** Raporunun en değerli kısmı tesis adıdır. Teyit edilmiş bir ticari unvan bulmak için tüm kanıtları dikkatle incele.
        3.  **Güncelliği Koru:** Sadece sana belirtilen tarih aralığına odaklan.
        4.  **Kanıta Daya:** Her bir bilgiyi, arama sonuçlarından bulduğun bir kaynağa dayandır.
        5.  **Standartlara Uy:** Nihai çıktın, SADECE istenen formatta bir Markdown tablosu olmalıdır.

        İSTENEN ÇIKTI FORMATI:
        | Sıra | Tarih | Şirket Adı | Açıklama ve Teyit | Hasarın Etkisi | Referans URL |
        |------|-------|------------|-------------------|----------------|--------------|
        """),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    # 4. Adım: Ajanı İnşa Et
    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)

    # 5. Adım: Ajanı Çalıştır
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
