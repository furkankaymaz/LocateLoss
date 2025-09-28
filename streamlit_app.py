import streamlit as st
import pandas as pd
from datetime import datetime
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

st.set_page_config(page_title="Hasar Olay Haritası", layout="wide", page_icon="🧭")

# ---------- UI ----------
st.title("Endüstriyel Hasar İstihbaratı — Olay Haritası & Detay Panosu")
st.caption("Kaynaklı, alıntılı ve haritalı olay listesi. Alıntılar doğrudan haberlerden, linkler tıklanabilir.")

uploaded = st.file_uploader("CSV yükleyin (UTF-8).", type=["csv"])
if uploaded is None:
    st.info("Örnek: yukarıdaki tablo başlıklarıyla hazırlanmış CSV yükleyin.")
    st.stop()

df = pd.read_csv(uploaded).fillna("")

# Normalize column names (tolerant)
def col(name):
    for c in df.columns:
        if c.lower().strip() == name.lower().strip():
            return c
    return name  # fallback

COL_DATE = col("Tarih")
COL_CITY = col("İl/İlçe")
COL_ADDR = col("OSB/Mevki (Parsel/Adres)")
COL_NAME = col("Tesis Adı (Alternatifler)")
COL_SECTOR = col("Sektör/Tip")
COL_EVENT = col("Olay Türü")
COL_METHOD = col("Doğrulama Yöntemi (A/B)")
COL_CONF = col("Doğruluk Oranı")
COL_CAUSE = col("Çıkış Şekli")
COL_PD = col("PD Etkisi")
COL_BI = col("BI Etkisi")
COL_QUOTE = col("Alıntı")
COL_SOURCES = col("Kaynaklar")
COL_URLS = col("Kaynak URL’leri")
COL_LAT = "Lat" if "Lat" in df.columns else None
COL_LON = "Lon" if "Lon" in df.columns else None

# Parse dates if possible
def try_parse_date(x):
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(x), fmt).date()
        except:
            pass
    return None

df["_date"] = df[COL_DATE].apply(try_parse_date)
min_d = df["_date"].min()
max_d = df["_date"].max()

# ---------- Sidebar Filters ----------
with st.sidebar:
    st.subheader("Filtreler")
    date_range = st.date_input("Tarih aralığı", value=(min_d, max_d) if min_d and max_d else None)
    cities = sorted([c for c in df[COL_CITY].unique() if c])
    city_sel = st.multiselect("İl/İlçe", cities, default=cities[:])
    events = sorted([e for e in df[COL_EVENT].unique() if e])
    event_sel = st.multiselect("Olay Türü", events, default=events[:])
    method_sel = st.multiselect("Doğrulama", ["A", "B"], default=["A","B"])
    st.markdown("---")
    show_neighbors = st.toggle("Çevre tesisleri olanları öne çıkar", value=True)

# Apply filters
q = df.copy()
if date_range and all(date_range):
    q = q[(q["_date"]>=date_range[0]) & (q["_date"]<=date_range[1])]
if city_sel:
    q = q[q[COL_CITY].isin(city_sel)]
if event_sel:
    q = q[q[COL_EVENT].isin(event_sel)]
if method_sel:
    q = q[q[COL_METHOD].str.upper().str.contains("|".join(method_sel))]

# ---------- Geocoding ----------
@st.cache_data(show_spinner=False)
def geocode_series(address_series):
    geolocator = Nominatim(user_agent="hasar-istihbarat/1.0")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)
    coords = {}
    for addr in address_series.unique():
        if not addr: 
            coords[addr] = (None, None)
            continue
        loc = geocode(addr + ", Türkiye")
        if loc:
            coords[addr] = (loc.latitude, loc.longitude)
        else:
            coords[addr] = (None, None)
    return coords

if COL_LAT and COL_LON:
    q["_lat"] = pd.to_numeric(q[COL_LAT], errors="coerce")
    q["_lon"] = pd.to_numeric(q[COL_LON], errors="coerce")
else:
    coords_map = geocode_series(q[COL_ADDR])
    q["_lat"] = q[COL_ADDR].map(lambda a: coords_map.get(a, (None, None))[0])
    q["_lon"] = q[COL_ADDR].map(lambda a: coords_map.get(a, (None, None))[1])

q_geo = q.dropna(subset=["_lat","_lon"])

# ---------- Map ----------
color_map = {
    "Yangın": "red",
    "Patlama + Yangın": "orange",
    "Kimyasal Sızıntı": "purple",
    "Çökme/Göçük": "darkblue",
    "Kran Devrilmesi": "cadetblue",
}
def get_color(evt):
    for k,v in color_map.items():
        if k.lower() in evt.lower():
            return v
    return "gray"

m = folium.Map(location=[39.0, 35.0], zoom_start=6, control_scale=True)
mc = MarkerCluster().add_to(m)

for _, r in q_geo.iterrows():
    title = f"{r[COL_NAME]} — {r[COL_EVENT]}"
    popup = folium.Popup(html=f"""
    <b>{r[COL_NAME]}</b><br>
    <i>{r[COL_SECTOR]}</i><br>
    <b>Olay:</b> {r[COL_EVENT]}<br>
    <b>Tarih:</b> {r[COL_DATE]} — <b>İl/İlçe:</b> {r[COL_CITY]}<br>
    <b>Adres/OSB:</b> {r[COL_ADDR]}<br>
    <b>Çıkış şekli:</b> {r.get(COL_CAUSE,'')}<br>
    <b>PD:</b> {r.get(COL_PD,'')}<br>
    <b>BI:</b> {r.get(COL_BI,'')}<br>
    <b>Doğrulama:</b> {r[COL_METHOD]} ({r[COL_CONF]})
    """, max_width=420)
    folium.CircleMarker(
        location=[r["_lat"], r["_lon"]],
        radius=7,
        color=get_color(r[COL_EVENT]),
        fill=True, fill_opacity=0.9,
        popup=popup,
        tooltip=title
    ).add_to(mc)

st_folium(m, width=None, height=560)

# ---------- Cards / Table ----------
st.subheader("Olay kartları")
for _, r in q.sort_values(by="_date", ascending=False).iterrows():
    with st.container(border=True):
        st.markdown(f"### {r[COL_NAME]} — **{r[COL_EVENT]}**")
        st.markdown(f"**Tarih:** {r[COL_DATE]}  •  **İl/İlçe:** {r[COL_CITY]}  •  **Doğrulama:** `{r[COL_METHOD]}`  •  **Doğruluk:** {r[COL_CONF]}")
        st.markdown(f"**Adres/OSB:** {r[COL_ADDR]}  \n**Sektör:** {r[COL_SECTOR]}")
        cols = st.columns(3)
        cols[0].markdown(f"**Çıkış şekli**  \n{r.get(COL_CAUSE,'')}")
        cols[1].markdown(f"**PD etkisi**  \n{r.get(COL_PD,'')}")
        cols[2].markdown(f"**BI etkisi**  \n{r.get(COL_BI,'')}")
        if r.get(COL_QUOTE, ""):
            st.markdown(f"> {r[COL_QUOTE]}")
        # Source badges
        urls = [u.strip() for u in str(r.get(COL_URLS, "")).split(";") if u.strip()]
        labels = [s.strip() for s in str(r.get(COL_SOURCES, "")).split("·")]
        if urls:
            st.write("**Kaynaklar:**", " ".join([f"[{labels[i] if i < len(labels) else 'Kaynak'}]({u})" for i,u in enumerate(urls)]))

st.caption("Not: B kayıtlarında adres/OSB + resmî firma rehberi/harita eşleşmesi ile doğrulama yapılmıştır. Ek teyit bulunursa A’ya yükseltilir.")
