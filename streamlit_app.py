 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a//dev/null b/streamlit_app.py
index 0000000000000000000000000000000000000000..ee23cb913961c2314a98b2d578122997f5296f60 100644
--- a//dev/null
+++ b/streamlit_app.py
@@ -0,0 +1,265 @@
+"""Streamlit application for analysing industrial incidents via the Grok API.
+
+This app queries the Grok Code Fast model for incidents that occurred in the
+last 30 days, enriches the events with neighbour information, and visualises
+the results both in a table and on a Folium map.
+"""
+
+from __future__ import annotations
+
+import json
+from datetime import datetime, timedelta
+from typing import Iterable, Optional
+
+import pandas as pd
+import streamlit as st
+from folium import Map, Marker
+from geopy.distance import geodesic
+from openai import OpenAI
+from streamlit_folium import folium_static
+
+
+# ---------------------------------------------------------------------------
+# Configuration
+# ---------------------------------------------------------------------------
+
+MODEL = "grok-code-fast-1"
+
+# Hard-coded locations for organised industrial zones (OSB) and similar sites.
+OSB_LIST: dict[str, tuple[float, float]] = {
+    "Kayseri OSB": (38.75, 35.50),
+    "Bor OSB": (37.85, 34.55),
+    "Kemalpaşa OSB": (38.47, 27.42),
+    "Balıkesir OSB": (39.65, 27.88),
+    "İSTOÇ İstanbul": (41.05, 28.82),
+    "Aliağa OSB": (38.80, 27.00),
+    "Soma Termik": (39.15, 27.60),
+    "Buca Sanayi": (38.40, 27.13),
+}
+
+
+# ---------------------------------------------------------------------------
+# Utility functions
+# ---------------------------------------------------------------------------
+
+def render_prompt() -> str:
+    """Build the prompt sent to the Grok API."""
+
+    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
+    end_date = datetime.now().strftime("%Y-%m-%d")
+
+    return f"""
+    Türkiye'de {start_date}-{end_date} arası endüstriyel tesislerde (fabrika, OSB, enerji
+    santrali) sigortaya konu risklerden (yangın, deprem, patlama, sızıntı, su basması,
+    makine kırılması) etkilenen olayları listele. Kaynaklar: Teyitli haberler (AA, DHA,
+    NTV, Hürriyet) + X postları/kullanıcı raporları (güvenilir hesaplar, min_retweets:5).
+    Küçük olayları ele. Her olay için JSON listesi döndür (yalnızca JSON cevabı ver):
+    - olay_tarihi (YYYY-MM-DD)
+    - tesis_adi_turu (Ad + (Tür))
+    - adres (İl/İlçe/Mahalle, approx. koordinat)
+    - hasar_etkisi (Detay: Sebep, can kaybı, TL hasar tahmini, üretim etkisi, sigorta notu)
+    - dogruluk_orani (%95 - Kaynaklar: NTV + X postları + Valilik, 3+ kaynak)
+    - komsu_tesisler (5km risk: Örnek tesisler, duman/sıçrama etki, etkilenme raporu)
+    En fazla 12 olayı kapsayan bir liste üret. Veri yoksa boş liste [].
+    """
+
+
+def parse_events(content: str) -> pd.DataFrame:
+    """Parse the JSON response content into a DataFrame."""
+
+    try:
+        events_json = json.loads(content)
+    except json.JSONDecodeError:
+        st.error("Grok API'den beklenen JSON formatında cevap alınamadı.")
+        return pd.DataFrame()
+
+    if isinstance(events_json, dict):
+        # A single object may be returned—wrap it into a list for consistency.
+        events_json = [events_json]
+
+    if not isinstance(events_json, list):
+        st.error("Grok API beklenmeyen bir format döndürdü.")
+        return pd.DataFrame()
+
+    df = pd.DataFrame(events_json)
+    if df.empty:
+        return df
+
+    if "olay_tarihi" in df.columns:
+        df["olay_tarihi"] = pd.to_datetime(df["olay_tarihi"], errors="coerce")
+
+    return df
+
+
+def resolve_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
+    """Return the first column name that exists in the DataFrame."""
+
+    for column in candidates:
+        if column in df.columns:
+            return column
+    return None
+
+
+def find_neighbors(lat: Optional[float], lng: Optional[float]) -> str:
+    """Return a formatted string describing OSB neighbours within 5 km."""
+
+    if lat is None or lng is None:
+        return "Konum yok"
+
+    event_pos = (lat, lng)
+    neighbours: list[str] = []
+
+    for osb, pos in OSB_LIST.items():
+        distance_km = geodesic(event_pos, pos).km
+        if distance_km < 5:
+            neighbours.append(f"{osb} ({distance_km:.1f} km - Risk: Yüksek)")
+
+    return "; ".join(neighbours) if neighbours else "Komşu yok"
+
+
+def enrich_events(df: pd.DataFrame) -> pd.DataFrame:
+    """Add neighbour information and harmonise column names."""
+
+    if df.empty:
+        return df
+
+    df = df.copy()
+
+    lat_column = resolve_column(df, ["lat", "latitude", "enlem"])
+    lng_column = resolve_column(df, ["lng", "lon", "longitude", "boylam"])
+    neighbour_column = resolve_column(df, ["komşu_tesisler", "komsu_tesisler"])
+
+    def compute_neighbour(row: pd.Series) -> str:
+        if neighbour_column and pd.notna(row.get(neighbour_column)):
+            return row.get(neighbour_column)
+
+        lat_value = row.get(lat_column) if lat_column else None
+        lng_value = row.get(lng_column) if lng_column else None
+        if pd.notna(lat_value) and pd.notna(lng_value):
+            return find_neighbors(float(lat_value), float(lng_value))
+        return "Komşu yok"
+
+    df["komşu_tesisler"] = df.apply(compute_neighbour, axis=1)
+
+    return df
+
+
+def build_display_df(df: pd.DataFrame) -> pd.DataFrame:
+    """Prepare the DataFrame for displaying in the Streamlit UI."""
+
+    display_columns = [
+        column
+        for column in [
+            "olay_tarihi",
+            "tesis_adi_turu",
+            "adres",
+            "hasar_etkisi",
+            "dogruluk_orani",
+            "komşu_tesisler",
+        ]
+        if column in df.columns
+    ]
+
+    display_df = df[display_columns].copy()
+
+    if "olay_tarihi" in display_df.columns:
+        display_df = display_df.sort_values("olay_tarihi", ascending=False)
+
+    return display_df
+
+
+def render_map(df: pd.DataFrame) -> None:
+    """Render a folium map for events that contain latitude and longitude."""
+
+    lat_column = resolve_column(df, ["lat", "latitude", "enlem"])
+    lng_column = resolve_column(df, ["lng", "lon", "longitude", "boylam"])
+
+    if not lat_column or not lng_column:
+        st.warning("Harita için konum verisi yok.")
+        return
+
+    map_df = df.dropna(subset=[lat_column, lng_column])
+    if map_df.empty:
+        st.warning("Harita için konum verisi yok.")
+        return
+
+    event_map = Map(location=[39, 35], zoom_start=6)
+
+    for _, row in map_df.iterrows():
+        location = [float(row[lat_column]), float(row[lng_column])]
+        popup_text = "\n".join(
+            f"{col}: {row[col]}"
+            for col in [
+                "olay_tarihi",
+                "tesis_adi_turu",
+                "adres",
+                "hasar_etkisi",
+                "dogruluk_orani",
+                "komşu_tesisler",
+            ]
+            if col in row and pd.notna(row[col])
+        )
+        Marker(location=location, popup=popup_text or None).add_to(event_map)
+
+    folium_static(event_map)
+
+
+@st.cache_data(ttl=86400)
+def get_grok_events(api_key: str) -> pd.DataFrame:
+    """Query the Grok API and return the resulting events."""
+
+    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
+
+    try:
+        response = client.chat.completions.create(
+            model=MODEL,
+            messages=[{"role": "user", "content": render_prompt()}],
+            max_tokens=1200,
+            temperature=0.0,
+            top_p=0.2,
+        )
+    except Exception as exc:  # noqa: BLE001 - propagate the error to the UI
+        st.error(f"Grok Hatası: {exc}")
+        return pd.DataFrame()
+
+    content = response.choices[0].message.content.strip()
+    return parse_events(content)
+
+
+# ---------------------------------------------------------------------------
+# Streamlit UI
+# ---------------------------------------------------------------------------
+
+
+st.set_page_config(page_title="Endüstriyel Tesis Hasar Analizi", layout="wide")
+
+st.title("🚨 Son 30 Gün Endüstriyel Tesis Hasar Analizi")
+st.markdown(
+    "Grok Code Fast API entegrasyonuyla (düşük maliyetli) X/Web taraması. Tablo ve "
+    "harita gösterir."
+)
+
+api_key = st.secrets.get("GROK_API_KEY")
+
+if not api_key:
+    st.error("Grok API anahtarı Streamlit secrets içerisinde bulunamadı.")
+    st.stop()
+
+if st.button("Analiz Et (Son 30 Gün)"):
+    with st.spinner("Grok ile tarama yapılıyor... (X ve web kaynakları çaprazlandı)"):
+        events_df = get_grok_events(api_key)
+
+        if events_df.empty:
+            st.warning("Son 30 günde önemli olay tespit edilemedi.")
+        else:
+            events_df = enrich_events(events_df)
+
+            st.subheader("Son 30 Gün Hasarlar")
+            st.dataframe(build_display_df(events_df))
+
+            render_map(events_df)
+
+st.caption(
+    "Kaynaklar: Grok Code Fast API (X postları + web haberleri). Günlük cache ile "
+    "optimizasyon."
+)
 
EOF
)
