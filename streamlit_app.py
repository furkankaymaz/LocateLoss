**requirements.txt**

```
streamlit==1.39.0
pandas==2.2.2
folium==0.17.0
streamlit-folium==0.21.0
geopy==2.4.1
```

**app.py**

```python
import streamlit as st
import pandas as pd
from io import StringIO
from datetime import datetime
import re

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

st.set_page_config(page_title="Hasar Olay Haritası", layout="wide", page_icon="🧭")

# =========================
# 1) Gömülü TSV (veri)
# =========================
EMBEDDED_TSV = """Tarih\tİl/İlçe\tOSB/Mevki (Parsel/Adres)\tTesis Adı (Alternatifler)\tSektör/Tip\tOlay Türü\tDoğrulama Yöntemi (A/B)\tDoğruluk Oranı\tKaynaklar
26.06.2025\tBursa/Mustafakemalpaşa\tOrta Mah., Ekşikara Mevkii\tBatim Kimya Sanayi İthalat İhracat Ltd. Şti.\tPlastik / Geri Dönüşüm\tYangın\tA\t100%\tAA · GZT
26.06.2025\tAydın/Efeler\tÇeştepe Mah., Cumhuriyet Cad.\tŞahane Group İnşaat Sanayi ve Ticaret Ltd. Şti.\tİnşaat Malzemeleri / Depo\tYangın\tB\t80%\tAydın Denge · Yandex Maps
27.06.2025\tBatman/Merkez\tBatman OSB\tFernas Gıda Sanayi ve Ticaret A.Ş. (Lavi Meyve Suyu Fabrikası)\tGıda / Meyve Suyu\tYangın\tA\t100%\tBatman Valiliği (X) · Batman Sonsöz
30.06.2025\tAnkara/Sincan\tSincan Sanayi Sitesi\tAtık Kağıt Geri Dönüşüm Tesisi\tGeri Dönüşüm / Kağıt\tYangın\tB\t90%\tEtik Haber · AA
30.06.2025\tEskişehir/Odunpazarı\tEskişehir OSB, 14. Cad. No:18-20\tKorel Elektronik Sanayi ve Ticaret A.Ş.\tBeyaz Eşya Parçaları\tYangın\tA\t95%\tOxu.az · Korel (Adres)
2.07.2025\tBurdur/Bucak\tOğuzhan Sanayi Sitesi (Sanayi Mah.)\tOğuzhan Sanayi Sitesi Atık Ayrıştırma/Depolama Tesisi\tGeri Dönüşüm / Depo\tYangın\tB\t85%\tÇağdaş Burdur · Habertürk
7.07.2025\tAksaray/Merkez\tAksaray OSB (Taşpınar), Erenler OSB 6. Sk. No:9/2\tFentes Isı Sistemleri Sanayi ve Ticaret Ltd. Şti. (Fentes Boyler/Termosifon)\tIsı Sistemleri / Boyler-Termosifon\tKazan/Boiler Patlağı\tA\t98%\tFentes (Ticari Bilgiler) · AA
9.07.2025\tTekirdağ/Çorlu\tHatip Mah., Ali Osman Çelebi Bulvarı\tION Reklam Yapı Ürünleri A.Ş.\tKompozit Panel / Reklam\tYangın\tA\t85%\tHürriyet · ION Yapı (Adres)
15.07.2025\tBolu/Karacasu\tKaracasu Beld., Büyük Berk Mah., Fabrika Cad.\tŞafak Enjektör Medikal Ürünler San. Tic. A.Ş.\tMedikal Üretim\tYangın\tA\t95%\tBolu Valiliği (X) · Memurlar.net
17.07.2025\tElazığ/Merkez\tElazığ OSB\tKaraca Harput Kireç Sanayi ve Ticaret A.Ş.\tKireç\tYangın\tA\t85%\tHürriyet · Elazığ OSB
18.07.2025\tKocaeli/Dilovası\tÇerkesli OSB (İMES OSB, 20. Cad. çevresi)\tAKTL Asil Kataforez Metal Sanayi ve Ticaret A.Ş. (AKTL Asil Kataforez)\tMetal Kaplama / KTL\tYangın\tB\t88%\tDHA · AA
21.07.2025\tBursa/Osmangazi\tVeysel Karani Mah., Sena Sk.\tArden Konfeksiyon İnşaat Sanayi ve Ticaret Ltd. Şti. (Arden Tekstil)\tTekstil\tYangın\tB\t85%\tHürriyet · DHA
22.07.2025\tBursa/Nilüfer\tHasanağa OSB (HOSAB)\tKarsan Otomotiv Sanayii ve Ticaret A.Ş.\tOtomotiv (Otobüs)\tYangın\tA\t97%\tİHA · Paratic
22.07.2025\tKayseri/Melikgazi\tKayseri OSB, 33. Cad. No:28\tVenti Mobilya Tekstil Sanayi ve Ticaret Ltd. Şti.\tMobilya\tYangın\tA\t100%\tKayseri Manşet · Venti (İletişim)
23.07.2025\tKocaeli/İzmit\tSanayi Mahallesi\tKompozit Ürünler Deposu\tKompozit\tYangın\tB\t80%\tHürriyet · AA
25.07.2025\tAnkara/Sincan\tASO 1. OSB (Akhun Cd. çevresi)\tAkkayalar Konveyör Sanayi ve Ticaret A.Ş.\tMetal / Makine\tYangın\tB\t90%\tHürriyet · DHA
29.07.2025\tİstanbul/Çekmeköy\tAlemdağ Mah., Havacılar Cd. No:6\tİnter Sünger Kimya Sanayi ve Ticaret A.Ş.\tKimya / Sünger-Elyaf\tYangın\tA\t100%\tAA · İstanbul İtfaiyesi
30.07.2025\tİstanbul/Arnavutköy\tBolluca Mahallesi\tRenksan Plastik Sünger Fabrikası\tPlastik / Sünger\tYangın\tA\t95%\tArnavutköy Kaymakamlığı · AA
31.07.2025\tKocaeli/Körfez\tKutluca Köyü, Emmezli Mah.\tCengiz Bilecik’e ait depo/tesis\tTarım / Depo\tYangın\tB\t90%\tT24 · Demokrat Kocaeli
3.08.2025\tTekirdağ/Ergene\tAvrupa Serbest Bölgesi\tN2O GAS AHMET SOĞUKOĞLU (Anestezi Gazı Üretim Tesisi)\tKimya / Gaz Üretimi\tPatlama + Yangın\tA\t100%\tAA · Bianet
5.08.2025\tKonya/Çumra\tÇumra OSB (İstiklal OSB, Konevi No:10/1)\tGNC Alüminyum Dış Ticaret Korkuluk Sistemleri İnş. Müh. Ltd. Şti.\tAlüminyum / Ekstrüzyon\tYangın\tA\t90%\tÇumra OSB Firma Listesi · GNC (Katalog/Adres)
6.08.2025\tÇorum/Merkez\tÇorum OSB\tErsa Tekstil Konfeksiyon Sanayi ve Ticaret A.Ş.\tTekstil\tYangın\tA\t96%\tTRT Haber · AA
6.08.2025\tKaraman/Merkez\tKaraman OSB\tEldem Mobilya Sanayi ve Ticaret Ltd. Şti.\tMobilya\tYangın\tB\t90%\tKaraman24 · Genç Karaman
10.08.2025\tBalıkesir/Gönen\tHasanbey Mah.\tTek-Süt Süt Ürünleri Sanayi ve Ticaret A.Ş.\tGıda / Süt Ürünleri\tYangın\tA\t100%\tYenigün Balıkesir · İHA
10.08.2025\tKocaeli/Darıca\tOsmangazi Mah., Çelikoğlu Cd.\tEndüstriyel Mutfak Ekipmanları Fabrikası\tEndüstriyel Mutfak\tYangın\tB\t90%\tAA · Kocaeli Fikir
10.08.2025\tİzmir/Aliağa\tALOSBİ (Aliağa OSB)\tHABAŞ Sınai ve Tıbbi Gazlar İstihsal Endüstrisi A.Ş.\tMetal İşleme\tYangın\tB\t95%\tİzmir İtfaiyesi (IG) · Hibya
13.08.2025\tKocaeli/Kartepe\tUzunçiftlik Mah., Mihriban Sk. No:17\tAkademi Çevre Entegre Atık Yönetimi Endüstri San. ve Tic. A.Ş.\tGeri Dönüşüm\tYangın\tA\t100%\tKocaeli Fikir · Akademi Çevre (Adres)
13.08.2025\tManisa/Yunusemre\tManisa OSB, 1. Kısım (50. Yıl Cd. çevresi)\tİs Makina Isı Ürünleri ve Kaplama Sanayi ve Ticaret Ltd. Şti.\tMetal Kaplama / Isı Ürünleri\tKimyasal Sızıntı (Buhar)\tA\t95%\tİHA/Yeni Asır · MOSB Firma Listesi
14.08.2025\tEskişehir/Odunpazarı\tEMKO Sanayi Bölgesi (Geri Dönüşümcüler Sitesi)\tEMKO Geri Dönüşüm Tesisleri\tGeri Dönüşüm\tYangın\tB\t100%\tMilliyet · Eskişehir BB
16.08.2025\tGaziantep/Şehitkamil\t2. OSB\tDilek Halı İthalat İhracat Sanayi ve Ticaret A.Ş.\tTekstil / Halı\tYangın\tB\t90%\tYerel Haber · Gaziantep Valiliği (X)
17.08.2025\tGaziantep/Şehitkamil\t2. OSB, 83230–83211 Cad.\tAkpınar Geri Dönüşüm Sanayi ve Ticaret Ltd. Şti. (Dilek Halı yakını)\tGeri Dönüşüm / Halı\tYangın\tA\t95%\tİHA · Google Maps
18.08.2025\tGaziantep/Şehitkamil\t2. OSB\tGeri Dönüşüm Fabrikası (2. OSB)\tGeri Dönüşüm\tYangın\tB\t90%\tFatma Şahin (X) · Yeni Journal (X)
19.08.2025\tİzmir/Torbalı\tYazıbaşı Mah.\tTermoteks Sanayi ve Ticaret A.Ş.\tPlastik / Yalıtım\tYangın\tA\t100%\tTorbalı Güncel · İHA
28.08.2025\tİstanbul/Arnavutköy\tYassıören Mah., Bayındır Cd., Sarıgazi Sk.\tMatbaa/Kağıtçılık & Geri Dönüşüm Tesisi\tKağıt / Ambalaj\tYangın\tB\t85%\tAA · İBB İtfaiye
31.08.2025\tKayseri/Melikgazi\tKayseri OSB, 12. Cad. (bölge)\tUhud Teknik Hırdavat Sanayi ve Ticaret Ltd. Şti.\tHırdavat / Depo\tPatlama + Yangın\tA\t95%\tDeniz Postası · Kayseri Bugün
2.09.2025\tİstanbul/Bağcılar\tMahmutbey Mah., İSTOÇ 10. Ada, 2428. Sk.\tİSTOÇ Ticaret Merkezi (Depo/İşyeri)\tDepo / İşyeri\tYangın\tB\t85%\tHürriyet · AA
3.09.2025\tKayseri/Melikgazi\tKayseri OSB, 10. Cad.\tMilkay Tekstil Sanayi ve Ticaret A.Ş.\tTekstil / Keçe\tYangın\tB\t95%\tAA · Milkay
3.09.2025\tTekirdağ/Ergene\tVelimeşe OSB, 252. Sk. No:32/1\tSanal Tül Tekstil Sanayi ve Dış Ticaret Ltd. Şti.\tTekstil\tYangın\tB\t92%\tHürriyet · VOSB Firma Listesi
4.09.2025\tNiğde/Merkez\tNiğde OSB\tSaygın Ambalaj Sanayi ve Ticaret A.Ş.\tPlastik / Ambalaj\tYangın\tB\t95%\tEmrah Özdemir (X) · AA
8.09.2025\tMersin/Toroslar\tAkbelen Bulv., Hüseyin Okan Merzeci Mah.\tSes ve Görüntü Sistemleri Fabrikası\tElektronik\tYangın\tB\t85%\tOxu.az · AA
10.09.2025\tKocaeli/Dilovası\tDilovası OSB, Diliskelesi – Liman sahası\tPoliport Kimya Sanayi ve Ticaret A.Ş. (Poliport Limanı)\tKimya / Liman\tKimyasal Sızıntı\tA\t96%\tPoliport · Dünya
12.09.2025\tEdirne/Keşan\tPaşayiğit Mah., Keşan OSB Şantiyesi (Su Deposu)\tKeşan Organize Sanayi Bölgesi (OSB Su Deposu)\tOSB Altyapı / Su Deposu\tKimyasal Maruziyet (Zehirlenme)\tB\t80%\tYeni Ufuk · Nöbetçi Gazete
12.09.2025\tEskişehir/Odunpazarı\tAşağı Söğütönü Mevkii\tAşağı Söğütönü Kereste (Kereste Fabrikası)\tKereste\tYangın\tB\t100%\tEskişehir Haber (X) · İHA
12.09.2025\tSakarya/Akyazı\tKüçücek Mahallesi\tPlastik Geri Dönüşüm Tesisi\tPlastik / Geri Dönüşüm\tYangın\tB\t65%\tOxu.az · Akyazı Haber
12.09.2025\tManisa/Yunusemre\tMuradiye OSB\tTekeli Geri Dönüşüm Sanayi ve Ticaret A.Ş.\tMetal / Geri Dönüşüm\tYangın\tB\t85%\tEtki Haber · İHA
17.09.2025\tSamsun/Tekkeköy\tKirazlık Mah., Örnek Sanayi Sitesi\tÖztürk Kereste Sanayi ve Ticaret Ltd. Şti.\tKereste / Ağaç\tYangın\tA\t95%\tAA · Samsun Canlı Haber (IG)
17.09.2025\tBursa/Kestel\tEski Muradiye Mevkii\tEski Muradiye Ahşap (Ahşap Palet Fabrikası)\tAhşap / Palet\tYangın\tB\t100%\tYeni Marmara · Ankara Masası (X)
17.09.2025\tİzmir/Torbalı\tÖrnek Sanayi Mevkii\tÖrnek Sanayi Kereste (Kereste Fabrikası)\tKereste\tYangın\tB\t100%\tSamsun’un Sesi (X) · İz Gazete
18.09.2025\tİzmir/Gaziemir\tFatih Mah., Sarnıç Bölgesi, Çamlık Cd. No:10\tLucente Mobilya Sanayi ve Ticaret A.Ş.\tMobilya\tYangın\tA\t90%\tAA · Lucente (Adres)
18.09.2025\tİzmir/Buca\t659/14 Sokak (Mobilya Deposu)\tBuca Mobilya Deposu (Fatih Türker)\tMobilya / Depo\tYangın\tB\t95%\tAA (FB) · Habertürk
18.09.2025\tAksaray/Merkez\tOSB, Erenler Mah., Mehmet Altınsoy Bulv.\tTarhan Geri Dönüşüm Tesisi (Depo)\tGeri Dönüşüm / Depo\tYangın\tB\t95%\tYeni Şafak · Yandex Derleme
20.09.2025\tKayseri/Melikgazi\tKayseri OSB, Sazyolu Cd.\tVenti Mobilya Tekstil Sanayi ve Ticaret Ltd. Şti. (2. tesis)\tMobilya\tYangın\tA\t100%\tAA · Sonses TV
20.09.2025\tİstanbul/Başakşehir\tİkitelli OSB, Depo Ardiyeciler Sanayi Sitesi (DEPARKO)\tDeparko Nakliye Deposu (Van Sürat Kargo/SHL Sahil Nakliyat)\tLojistik / Kargo\tYangın\tA\t95%\tAA · Dünya
20.09.2025\tTekirdağ/Kapaklı\tYanıkağıl Mahallesi\tPalet Depolama/Üretim Sahası (Yanıkağıl)\tAhşap / Palet\tYangın\tB\t80%\tYandex Haber · Gerçek Gündem
21.09.2025\tAdana/Seyhan\tKüçükdikili Mahallesi\tKüçükdikili Geri Dönüşüm Fabrikası\tGeri Dönüşüm\tYangın\tB\t100%\tGZT · Yeni Akit
24.09.2025\tManisa/Yunusemre\tManisa OSB, Cumhuriyet Blv. (Arçelik Kampüsü)\tArçelik Anonim Şirketi (Arçelik Manisa Fabrikası)\tBeyaz Eşya / Fabrika\tÇökme/Kran Devrilmesi\tB\t85%\tManisa Kulis Haber · IG yerel
25.09.2025\tManisa/Yunusemre\tManisa OSB (Vestel City)\tVestel Beyaz Eşya Sanayi ve Ticaret A.Ş. (Vestel City)\tDayanıklı Tüketim / Beyaz Eşya\tKran Devrilmesi\tB\t80%\tManisa Kulis Haber · Vestel Beyaz Eşya (Üye Kaydı)
25.09.2025\tZonguldak/Kilimli\tKaradon Müessesesi, -263 kotu\tTürkiye Taşkömürü Kurumu Karadon Müessese Müdürlüğü\tMaden / Kömür Ocağı\tÇökme (Göçük)\tA\t98%\tAA · DHA
25.09.2025\tZonguldak/Kilimli\tÇatalağzı, ZETES Termik Santral Sahası\tEren Enerji Elektrik Üretim A.Ş. (Çatalağzı Termik Santrali)\tEnerji / Termik Santral\tKazan/Boiler Buhar Hattı Patlağı\tA\t96%\tZ Haber · Eren Enerji
"""

# =========================
# 2) Yardımcılar
# =========================
def parse_date(s):
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(s), fmt).date()
        except Exception:
            pass
    return None

def ensure_columns(df):
    needed = [
        "Çıkış Şekli", "PD Etkisi", "BI Etkisi", "Alıntı",
        "Kaynak URL’leri", "Çevre Tesisler", "Lat", "Lon"
    ]
    for c in needed:
        if c not in df.columns:
            df[c] = ""
    return df

def normalize_cols(df):
    def col(name):
        for c in df.columns:
            if c.lower().strip() == name.lower().strip():
                return c
        return name
    return {
        "Tarih": col("Tarih"),
        "IlIlce": col("İl/İlçe"),
        "Addr": col("OSB/Mevki (Parsel/Adres)"),
        "Name": col("Tesis Adı (Alternatifler)"),
        "Sector": col("Sektör/Tip"),
        "Event": col("Olay Türü"),
        "Method": col("Doğrulama Yöntemi (A/B)"),
        "Conf": col("Doğruluk Oranı"),
        "Sources": col("Kaynaklar"),
        "Cause": col("Çıkış Şekli"),
        "PD": col("PD Etkisi"),
        "BI": col("BI Etkisi"),
        "Quote": col("Alıntı"),
        "URLs": col("Kaynak URL’leri"),
        "Neighbors": col("Çevre Tesisler"),
        "Lat": "Lat",
        "Lon": "Lon",
    }

# Sık görülen OSB koordinatları (yaklaşık merkezler) — varsa bunları kullan, yoksa geocode
OSB_COORDS = {
    "Kayseri OSB": (38.779, 35.344),
    "Batman OSB": (37.897, 41.140),
    "Manisa OSB": (38.663, 27.405),
    "Hasanağa OSB": (40.208, 28.749),
    "Dilovası OSB": (40.793, 29.534),
    "ALOSBİ": (38.780, 26.970),
    "Aliağa OSB": (38.780, 26.970),
    "Velimeşe OSB": (41.126, 27.954),
    "Niğde OSB": (37.959, 34.716),
    "İkitelli OSB": (41.073, 28.804),
    "İSTOÇ": (41.063, 28.826),
    "Avrupa Serbest Bölgesi": (41.189, 27.729),
    "Çorum OSB": (40.604, 34.985),
    "Karaman OSB": (37.164, 33.244),
    "Gaziantep 2. OSB": (37.123, 37.388),
    "Aksaray OSB": (38.280, 34.275),
    "Keşan OSB": (40.849, 26.631),
}

@st.cache_data(show_spinner=False)
def geocode_address(addr):
    # OSB kısmi eşleşme ile hızlı koordinat
    for key, (lat, lon) in OSB_COORDS.items():
        if key.lower() in addr.lower():
            return lat, lon
    geolocator = Nominatim(user_agent="hasar-istihbarat/1.0")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, swallow_exceptions=True)
    loc = geocode(addr + ", Türkiye")
    if loc:
        return loc.latitude, loc.longitude
    return None, None

@st.cache_data(show_spinner=False)
def geocode_df(df, C):
    lat = df[C["Lat"]].astype(str).str.strip()
    lon = df[C["Lon"]].astype(str).str.strip()
    has_latlon = lat.ne("").sum() and lon.ne("").sum()
    out = df.copy()
    if has_latlon:
        out["_lat"] = pd.to_numeric(lat, errors="coerce")
        out["_lon"] = pd.to_numeric(lon, errors="coerce")
    else:
        coords = df[C["Addr"]].apply(lambda a: geocode_address(str(a)))
        out["_lat"] = coords.apply(lambda t: t[0])
        out["_lon"] = coords.apply(lambda t: t[1])
    return out

def infer_neighbors(df, C):
    """
    Sadece metinde AÇIKÇA belirtilen desenlerle (halüsinasyonsuz) ilişki kur:
    - '(2. tesis)' -> aynı adın baz hali
    - '(... yakını)' -> parantez içinde 'yakını' geçen isim
    Üretilen 'Çevre Tesisler' kolonuna ';' ile yazılır.
    """
    neighbors_map = {i: set() for i in df.index}
    names = df[C["Name"]].astype(str)

    # (2. tesis) -> baz isim
    for i, nm in names.items():
        if "(2. tesis)" in nm:
            base = nm.split("(2. tesis)")[0].strip()
            matches = [j for j, other in names.items() if j != i and base and base.lower() in other.lower() and "(2. tesis)" not in other]
            for j in matches:
                neighbors_map[i].add(names[j])
                neighbors_map[j].add(nm)

    # '(X yakını)'
    yakini_re = re.compile(r"\(([^)]+?)\s+yakını\)", flags=re.IGNORECASE)
    for i, nm in names.items():
        m = yakini_re.search(nm)
        if m:
            target = m.group(1).strip()
            matches = [j for j, other in names.items() if j != i and target.lower() in other.lower()]
            for j in matches:
                neighbors_map[i].add(names[j])
                neighbors_map[j].add(nm)

    # yaz
    neigh_col = []
    for i in df.index:
        neigh_col.append("; ".join(sorted(neighbors_map[i])) if neighbors_map[i] else "")
    return neigh_col

def event_color(evt):
    e = (evt or "").lower()
    if "patlama" in e and "yangın" in e: return "orange"
    if "kimyasal" in e: return "purple"
    if "çökme" in e or "göçük" in e: return "darkblue"
    if "kran" in e: return "cadetblue"
    if "yangın" in e: return "red"
    return "gray"

# =========================
# 3) Veri yükle & zenginleştir
# =========================
st.title("Endüstriyel Hasar İstihbaratı — Harita & Detay Panosu")
st.caption("Gömülü listeyi kullanır. İsterseniz kendi CSV/TSV dosyanızla da değiştirebilirsiniz.")

uploaded = st.file_uploader("İsteğe bağlı: Kendi CSV/TSV dosyanızı yükleyin (başlıklar uyumlu olmalı).", type=["csv", "tsv"])
if uploaded:
    # Seperator'ı anlamaya çalış
    raw = uploaded.read().decode("utf-8", errors="ignore")
    sep = "\t" if "\t" in raw else ","
    df = pd.read_csv(StringIO(raw), sep=sep).fillna("")
else:
    df = pd.read_csv(StringIO(EMBEDDED_TSV), sep="\t").fillna("")

df = ensure_columns(df)
C = normalize_cols(df)
# Tarih
df["_date"] = df[C["Tarih"]].apply(parse_date)

# Neighbors (sadece açıkça belirtilen desenlerden)
auto_neighbors = infer_neighbors(df, C)
# Kullanıcı 'Çevre Tesisler' kolonu varsa birleştir (tekrarları engelle)
base_neigh = df[C["Neighbors"]].astype(str).str.strip()
combined = []
for i, auto in enumerate(auto_neighbors):
    items = set()
    if base_neigh.iloc[i]:
        items.update([x.strip() for x in base_neigh.iloc[i].split(";") if x.strip()])
    if auto:
        items.update([x.strip() for x in auto.split(";") if x.strip()])
    combined.append("; ".join(sorted(items)))
df[C["Neighbors"]] = combined

# Geocode
df = geocode_df(df, C)
df_geo = df.dropna(subset=["_lat", "_lon"])

# =========================
# 4) Filtreler
# =========================
with st.sidebar:
    st.subheader("Filtreler")
    mind, maxd = df["_date"].min(), df["_date"].max()
    default_range = (mind, maxd) if pd.notna(mind) and pd.notna(maxd) else None
    date_range = st.date_input("Tarih aralığı", value=default_range)
    cities = sorted([x for x in df[C["IlIlce"]].unique() if str(x).strip()])
    city_sel = st.multiselect("İl/İlçe", cities, default=cities)
    events = sorted([x for x in df[C["Event"]].unique() if str(x).strip()])
    event_sel = st.multiselect("Olay Türü", events, default=events)
    method_sel = st.multiselect("Doğrulama", ["A","B"], default=["A","B"])
    show_neighbors = st.toggle("Çevre tesis bağlantılarını göster", value=True)

q = df.copy()
if date_range and isinstance(date_range, (list, tuple)) and len(date_range) == 2 and all(date_range):
    q = q[(q["_date"] >= date_range[0]) & (q["_date"] <= date_range[1])]
if city_sel:
    q = q[q[C["IlIlce"]].isin(city_sel)]
if event_sel:
    q = q[q[C["Event"]].isin(event_sel)]
if method_sel:
    q = q[q[C["Method"]].str.upper().str.contains("|".join(method_sel))]

q_geo = q.dropna(subset=["_lat", "_lon"])

# =========================
# 5) Harita
# =========================
st.subheader("Harita")
m = folium.Map(location=[39.0, 35.0], zoom_start=6, control_scale=True)
mc = MarkerCluster().add_to(m)

# İsim -> koordinat haritası (komşular için gerekebilir)
name_to_xy = {}
for _, r in df_geo.iterrows():
    name_to_xy.setdefault(r[C["Name"]], (r["_lat"], r["_lon"]))

for _, r in q_geo.iterrows():
    title = f"{r[C['Name']]} — {r[C['Event']]}"
    popup_html = f"""
    <div style='width: 360px'>
      <b>{r[C['Name']]}</b><br>
      <i>{r[C['Sector']]}</i><br><br>
      <b>Olay:</b> {r[C['Event']]}<br>
      <b>Tarih:</b> {r[C['Tarih']]}<br>
      <b>İl/İlçe:</b> {r[C['IlIlce']]}<br>
      <b>Adres/OSB:</b> {r[C['Addr']]}<br>
      <b>Doğrulama:</b> {r[C['Method']]} ({r[C['Conf']]})<br>
      <b>Çıkış şekli:</b> {r[C['Cause']]}<br>
      <b>PD:</b> {r[C['PD']]}<br>
      <b>BI:</b> {r[C['BI']]}<br>
      <b>Kaynaklar:</b> {r[C['Sources']]}
    </div>
    """
    folium.CircleMarker(
        location=[r["_lat"], r["_lon"]],
        radius=7,
        color=event_color(r[C["Event"]]),
        fill=True, fill_opacity=0.9,
        popup=folium.Popup(popup_html, max_width=420),
        tooltip=title
    ).add_to(mc)

# Komşu bağlantıları (sadece açıkça belirtilen desenlerden üretilen/var olan isimlerle)
if show_neighbors:
    for _, r in q_geo.iterrows():
        neighs = [x.strip() for x in str(r[C["Neighbors"]]).split(";") if x.strip()]
        for nb in neighs:
            if nb in name_to_xy:
                lat1, lon1 = r["_lat"], r["_lon"]
                lat2, lon2 = name_to_xy[nb]
                if pd.notna(lat1) and pd.notna(lat2):
                    folium.PolyLine([[lat1, lon1], [lat2, lon2]], weight=2, opacity=0.7).add_to(m)

st_folium(m, width=None, height=580)

# =========================
# 6) Olay Kartları
# =========================
st.subheader("Olay Kartları")
for _, r in q.sort_values(by="_date", ascending=False).iterrows():
    with st.container():
        st.markdown(f"### {r[C['Name']]} — **{r[C['Event']]}**")
        st.markdown(
            f"**Tarih:** {r[C['Tarih']]}  •  **İl/İlçe:** {r[C['IlIlce']]}  •  "
            f"**Doğrulama:** `{r[C['Method']]}`  •  **Doğruluk:** {r[C['Conf']]}"
        )
        st.markdown(f"**Adres/OSB:** {r[C['Addr']]}  \n**Sektör:** {r[C['Sector']]}")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Çıkış şekli**  \n{r[C['Cause']]}")
        c2.markdown(f"**PD etkisi**  \n{r[C['PD']]}")
        c3.markdown(f"**BI etkisi**  \n{r[C['BI']]}")
        if str(r[C["Quote"]]).strip():
            st.markdown(f"> {r[C['Quote']]}")
        urls = [u.strip() for u in str(r[C["URLs"]]).split(";") if u.strip()]
        if urls:
            st.write("**Kaynak linkleri:**", "  ".join([f"[Link {i+1}]({u})" for i, u in enumerate(urls)]))
        neighs = [x.strip() for x in str(r[C["Neighbors"]]).split(";") if x.strip()]
        if neighs:
            st.markdown(f"**Çevre tesis(ler):** " + ", ".join(neighs))
        st.markdown("---")

# =========================
# 7) İndirilebilir çıktı
# =========================
st.subheader("Çıktı")
export_cols = [
    C["Tarih"], C["IlIlce"], C["Addr"], C["Name"], C["Sector"], C["Event"],
    C["Method"], C["Conf"], C["Sources"], C["Cause"], C["PD"], C["BI"],
    C["Quote"], C["URLs"], C["Neighbors"], "_lat", "_lon"
]
export_df = q[export_cols].rename(columns={"_lat": "Lat", "_lon": "Lon"})
csv_bytes = export_df.to_csv(index=False).encode("utf-8")
st.download_button("Filtrelenmiş CSV'yi indir", data=csv_bytes, file_name="hasar_olaylari_filtreli.csv", mime="text/csv")

st.caption("Not: Komşu/çevre tesis bağlantıları yalnızca haber metninde AÇIKÇA belirtilen desenlerden (örn. '(2. tesis)', '(... yakını)') türetilir.")
```
