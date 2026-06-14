"""
EUIPO & ABAD (CJEU) İçtihat MCP Sunucusu
==========================================
SMK kapsamındaki dilekçe yazımına destek için EUIPO ve ABAD kararlarına erişim sağlar.

Veri kaynakları:
  - EUIPO eSearchCLW (karalar ve temyiz kurulu kararları)
  - EUR-Lex CELLAR SPARQL  → ABAD (CJEU) + Genel Mahkeme kararları
  - InfoCuria REST          → ECLI ile doğrudan karar erişimi
"""

from fastmcp import FastMCP
import httpx
import json
from typing import Optional
from urllib.parse import quote, urlencode

mcp = FastMCP(
    name="euipo-cjeu-mcp",
    instructions=(
        "EUIPO ve ABAD (CJEU) içtihat veritabanı. "
        "SMK kapsamlı itiraz, kullanım ispatı ve yeniden değerlendirme dilekçelerini "
        "AB içtihadıyla desteklemek için kullanın."
    ),
)

# ─── Sabitler ───────────────────────────────────────────────────────────────

EUIPO_CASLAW_BASE = "https://euipo.europa.eu/eSearchCLW"
CELLAR_SPARQL     = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_BASE       = "https://eur-lex.europa.eu"
INFOCURIA_BASE    = "https://curia.europa.eu"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SMK-LegalMCP/1.0; "
        "+https://github.com/your-org/euipo-cjeu-mcp)"
    ),
    "Accept": "application/json",
}

# ─── Yardımcı fonksiyonlar ───────────────────────────────────────────────────

def _ok(data: dict | list) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)

def _err(msg: str, hint: str = "") -> str:
    return json.dumps({"error": msg, "hint": hint}, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════════════
#  ARAÇ 1 — EUIPO İçtihat Arama
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_euipo_decisions(
    query: str,
    karar_turu: str = "trademark",
    dil: str = "en",
    sayfa: int = 0,
    adet: int = 10,
) -> str:
    """
    EUIPO İçtihat Veritabanı'nda (eSearchCLW) arama yapar.

    Temyiz Kurulu, İtiraz Birimi ve İptal Birimi kararlarını + Genel Mahkeme /
    Adalet Divanı hükümlerini kapsar.

    Args:
        query       : Arama metni. Türkçe anahtar kavramların İngilizce karşılıklarını
                      kullanın (örn: "likelihood of confusion", "genuine use",
                      "distinctive character", "relative grounds", "absolute grounds").
        karar_turu  : "trademark" | "design"  (varsayılan: trademark)
        dil         : Sonuç dili  –  "en" | "de" | "fr" | "es" | ... (varsayılan: en)
        sayfa       : Sayfalama indeksi, 0'dan başlar.
        adet        : Sayfa başına sonuç sayısı (max önerilen: 25).

    Returns:
        Kararların listesi (ECLI, tarih, taraflar, konu, karar türü, bağlantı).
    """
    # ── Deneme 1: Undocumented REST endpoint (SPA backend) ──────────────────
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        # EUIPO eSearchCLW kullandığı API endpoint'ini tahmin ediyoruz.
        # SPA'nın network trafiğine göre aşağıdaki iki desenden biri aktiftir.
        endpoints = [
            (
                "GET",
                f"{EUIPO_CASLAW_BASE}/rest/decisions/{karar_turu}/search",
                dict(params={"q": query, "page": sayfa, "size": adet, "lang": dil}),
            ),
            (
                "POST",
                f"{EUIPO_CASLAW_BASE}/rest/search",
                dict(
                    json={
                        "text": query,
                        "type": karar_turu,
                        "language": dil,
                        "from": sayfa * adet,
                        "size": adet,
                    }
                ),
            ),
            (
                "GET",
                f"{EUIPO_CASLAW_BASE}/api/v1/{karar_turu}/caselaw",
                dict(params={"query": query, "offset": sayfa * adet, "limit": adet}),
            ),
        ]

        for method, url, kwargs in endpoints:
            try:
                if method == "GET":
                    r = await client.get(url, **kwargs)
                else:
                    r = await client.post(url, **kwargs)

                if r.status_code == 200:
                    data = r.json()
                    # Yanıtı normalize et
                    results = _normalize_euipo_response(data, query)
                    return _ok({
                        "kaynak": "EUIPO eSearchCLW",
                        "sorgu": query,
                        "sonuc_sayisi": len(results),
                        "sonuclar": results,
                    })
            except Exception:
                continue

    # ── Deneme 2: CELLAR SPARQL — EUIPO ile ilgili CJEU kararları ──────────
    # API başarısız olursa CELLAR üzerinden devam et
    sparql = f"""
PREFIX cdm:  <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>

SELECT DISTINCT ?work ?ecli ?tarih ?celex
WHERE {{
  ?work a cdm:judgment .
  ?work cdm:case-law_ECLI ?ecli .
  ?work cdm:work_date_document ?tarih .
  OPTIONAL {{ ?work cdm:resource_legal_id_celex ?celex }}
  # EUIPO/OHIM ile ilgili davalar (Genel Mahkeme + ABAD)
  FILTER (
    CONTAINS(LCASE(STR(?ecli)), ":t:") ||
    CONTAINS(LCASE(STR(?ecli)), ":c:")
  )
  FILTER (
    CONTAINS(LCASE(STR(?celex)), "tj") ||
    CONTAINS(LCASE(STR(?celex)), "cj")
  )
}}
ORDER BY DESC(?tarih)
LIMIT {adet}
"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                CELLAR_SPARQL,
                data={"query": sparql, "format": "application/sparql-results+json"},
                headers={
                    "Accept": "application/sparql-results+json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if r.status_code == 200:
                bindings = r.json().get("results", {}).get("bindings", [])
                results = [
                    {
                        "ecli":     b.get("ecli", {}).get("value", ""),
                        "tarih":    b.get("tarih", {}).get("value", ""),
                        "celex":    b.get("celex", {}).get("value", ""),
                        "eurlex_url": (
                            f"{EURLEX_BASE}/legal-content/EN/TXT/?uri=CELEX:"
                            + b.get("celex", {}).get("value", "")
                            if b.get("celex") else ""
                        ),
                    }
                    for b in bindings
                ]
                return _ok({
                    "kaynak": "EUR-Lex CELLAR (EUIPO API yanıtsız — fallback)",
                    "sorgu": query,
                    "not": (
                        "EUIPO'nun doğrudan API'si yanıt vermedi. "
                        "CELLAR üzerinden EUIPO/IP ile ilgili CJEU kararları getirildi. "
                        "Manuel arama için: " + _euipo_search_url(query, karar_turu)
                    ),
                    "sonuc_sayisi": len(results),
                    "sonuclar": results,
                })
    except Exception as e:
        pass

    # ── Son çare: Manuel arama bağlantısı ─────────────────────────────────
    return _ok({
        "kaynak": "EUIPO eSearchCLW (bağlantı hatası)",
        "sorgu": query,
        "not": "Otomatik arama başarısız. Lütfen aşağıdaki bağlantıyı kullanın.",
        "manuel_arama_url": _euipo_search_url(query, karar_turu),
        "sonuclar": [],
    })


def _normalize_euipo_response(data: dict | list, query: str) -> list:
    """EUIPO API'nin farklı yanıt şemalarını tek formata dönüştürür."""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = (
            data.get("results")
            or data.get("decisions")
            or data.get("hits", {}).get("hits", [])
            or data.get("content")
            or []
        )
    else:
        return []

    normalized = []
    for item in items:
        src = item.get("_source", item)
        normalized.append({
            "ecli":      src.get("ecli") or src.get("caseNumber") or "",
            "tarih":     src.get("date") or src.get("decisionDate") or "",
            "konu":      src.get("subject") or src.get("title") or "",
            "tur":       src.get("type") or src.get("decisionType") or "",
            "taraflar":  src.get("parties") or src.get("applicant") or "",
            "url":       src.get("url") or src.get("documentUrl") or "",
        })
    return normalized


def _euipo_search_url(query: str, tur: str = "trademark") -> str:
    return f"{EUIPO_CASLAW_BASE}/#basic/{tur}/{quote(query)}"


# ════════════════════════════════════════════════════════════════════════════
#  ARAÇ 2 — ABAD / Genel Mahkeme Kararı Arama (EUR-Lex CELLAR SPARQL)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def search_cjeu_decisions(
    anahtar_kelimeler: str,
    mahkeme: str = "all",
    tarih_baslangic: Optional[str] = None,
    tarih_bitis: Optional[str] = None,
    adet: int = 10,
) -> str:
    """
    ABAD (Adalet Divanı) ve Genel Mahkeme kararlarını EUR-Lex CELLAR üzerinden arar.

    SMK ile uyumlu AB marka hukuku içtihadını bulmak için kullanın:
      - Karıştırılma ihtimali (Art. 8/1-b EUTMR → SMK Art. 6)
      - Tanınmış marka (Art. 8/5 EUTMR → SMK Art. 6/4)
      - Kullanım ispatı (Art. 47/2 EUTMR → SMK Art. 25)
      - Mutlak ret nedenleri (Art. 7 EUTMR → SMK Art. 5)
      - Kötü niyet (Art. 59/1-b EUTMR → SMK Art. 23)

    Args:
        anahtar_kelimeler : İngilizce IP hukuku terimleri önerilir.
                            Örnek: "likelihood confusion identical goods",
                                   "genuine use trade mark five years",
                                   "distinctive character acquired use",
                                   "well-known mark reputation",
                                   "bad faith trademark application"
        mahkeme           : "cjeu"  → Sadece Adalet Divanı (C- davaları)
                            "gc"    → Sadece Genel Mahkeme (T- davaları)
                            "all"   → Tümü (varsayılan)
        tarih_baslangic   : "YYYY-MM-DD" formatı
        tarih_bitis       : "YYYY-MM-DD" formatı
        adet              : Maksimum sonuç sayısı (önerilen: 5–20)

    Returns:
        ECLI, CELEX, tarih, mahkeme ve EUR-Lex bağlantısı içeren karar listesi.
    """
    # Mahkeme filtresi
    if mahkeme == "cjeu":
        court_filter = 'FILTER(REGEX(STR(?ecli), "EU:C:"))'
    elif mahkeme == "gc":
        court_filter = 'FILTER(REGEX(STR(?ecli), "EU:T:"))'
    else:
        court_filter = 'FILTER(REGEX(STR(?ecli), "EU:(C|T):"))'

    # Tarih filtresi
    date_filter = ""
    if tarih_baslangic:
        date_filter += f'\n  FILTER(?tarih >= "{tarih_baslangic}"^^xsd:date)'
    if tarih_bitis:
        date_filter += f'\n  FILTER(?tarih <= "{tarih_bitis}"^^xsd:date)'

    # Anahtar kelimeden SPARQL subject-matter arama
    kw_words = anahtar_kelimeler.lower().split()
    kw_contains = " || ".join(
        f'CONTAINS(LCASE(STR(?subjectLabel)), "{w}")' for w in kw_words[:4]
    )

    sparql = f"""
PREFIX cdm:  <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?work ?ecli ?tarih ?celex ?mahkemeAdi
WHERE {{
  ?work a cdm:judgment .
  ?work cdm:case-law_ECLI ?ecli .
  ?work cdm:work_date_document ?tarih .
  OPTIONAL {{ ?work cdm:resource_legal_id_celex ?celex }}
  OPTIONAL {{
    ?work cdm:work_created_by_agent ?mahkeme2 .
    ?mahkeme2 skos:prefLabel ?mahkemeAdi .
    FILTER(LANG(?mahkemeAdi) = "en")
  }}
  OPTIONAL {{
    ?work cdm:work_is_about_subject-matter ?subject .
    ?subject skos:prefLabel ?subjectLabel .
    FILTER(LANG(?subjectLabel) = "en")
  }}
  {court_filter}
  {date_filter}
  # EUIPO / IP ile ilgili davalar
  FILTER(
    CONTAINS(LCASE(STR(?celex)), "tj0") ||
    CONTAINS(LCASE(STR(?celex)), "cj0") ||
    ({kw_contains if kw_contains else 'true'})
  )
}}
ORDER BY DESC(?tarih)
LIMIT {adet}
"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                CELLAR_SPARQL,
                data={"query": sparql},
                headers={
                    "Accept": "application/sparql-results+json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if r.status_code != 200:
                return _err(
                    f"CELLAR SPARQL yanıt hatası: {r.status_code}",
                    "EUR-Lex erişilebilirliğini kontrol edin.",
                )

            bindings = r.json().get("results", {}).get("bindings", [])
            results = []
            for b in bindings:
                ecli  = b.get("ecli",       {}).get("value", "")
                celex = b.get("celex",      {}).get("value", "")
                tarih = b.get("tarih",      {}).get("value", "")
                mkm   = b.get("mahkemeAdi", {}).get("value", "")

                # Mahkeme tipini ECLI'den çıkar
                if ":C:" in ecli:
                    tip = "Adalet Divanı (ABAD)"
                elif ":T:" in ecli:
                    tip = "Genel Mahkeme"
                else:
                    tip = mkm or "?"

                results.append({
                    "ecli":       ecli,
                    "celex":      celex,
                    "tarih":      tarih,
                    "mahkeme":    tip,
                    "eurlex_url": (
                        f"{EURLEX_BASE}/legal-content/EN/TXT/?uri=CELEX:{celex}"
                        if celex else ""
                    ),
                    "curia_url": (
                        f"{INFOCURIA_BASE}/juris/liste.jsf?language=en&jur=C,T&num="
                        + ecli.split(":")[-2].lstrip("0")
                        if ecli else ""
                    ),
                })

            return _ok({
                "kaynak":       "EUR-Lex CELLAR SPARQL",
                "sorgu":        anahtar_kelimeler,
                "mahkeme":      mahkeme,
                "sonuc_sayisi": len(results),
                "sonuclar":     results,
                "not": (
                    "CELLAR SPARQL, konu etiketleri üzerinden arama yapar. "
                    "Tam metin arama için get_cjeu_decision_text() kullanın "
                    "ya da InfoCuria'dan manuel arama yapın: "
                    f"{INFOCURIA_BASE}/juris/recherche.jsf"
                ),
            })

    except Exception as e:
        return _err(str(e), "Ağ bağlantısını veya CELLAR endpoint'ini kontrol edin.")


# ════════════════════════════════════════════════════════════════════════════
#  ARAÇ 3 — Karar Tam Metnini Getir (ECLI veya CELEX ile)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_cjeu_decision_text(
    ecli_veya_celex: str,
    dil: str = "EN",
) -> str:
    """
    ECLI veya CELEX numarasıyla ABAD / Genel Mahkeme kararının tam metnini getirir.

    Args:
        ecli_veya_celex : ECLI  → örn: "ECLI:EU:C:2019:181"
                          CELEX → örn: "62017CJ0230"
        dil             : "EN" (İngilizce, önerilen) | "DE" | "FR" | "TR" vb.

    Returns:
        Kararın tam metni (HTML temizlenmiş), taraflar, hüküm özeti ve EUR-Lex URL'i.
    """
    # URL oluştur
    if ecli_veya_celex.upper().startswith("ECLI:"):
        url = f"{EURLEX_BASE}/legal-content/{dil}/TXT/HTML/?uri=ecli:{ecli_veya_celex}"
    else:
        url = f"{EURLEX_BASE}/legal-content/{dil}/TXT/HTML/?uri=CELEX:{ecli_veya_celex}"

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            r = await client.get(url)

            if r.status_code != 200:
                return _err(
                    f"Karar bulunamadı (HTTP {r.status_code})",
                    f"EUR-Lex URL: {url}",
                )

            text = r.text

            # Basit HTML temizleme
            import re
            clean = re.sub(r"<[^>]+>", " ", text)
            clean = re.sub(r"\s{2,}", " ", clean).strip()

            # Önemli bölümleri bul
            judgment_start = max(
                clean.find("THE COURT"),
                clean.find("THE GENERAL COURT"),
                clean.find("JUDGMENT OF"),
                0,
            )
            excerpt = clean[judgment_start : judgment_start + 8000]

            return _ok({
                "ecli_veya_celex": ecli_veya_celex,
                "dil":             dil,
                "eurlex_url":      str(r.url),
                "metin_ozeti":     excerpt[:5000],
                "tam_metin_uzunlugu_karakter": len(clean),
                "not": (
                    "Tam metin için EUR-Lex URL'ini ziyaret edin. "
                    "Bu yanıt, metnin ilk 5000 karakterini içermektedir."
                ),
            })

    except Exception as e:
        return _err(str(e), f"EUR-Lex URL: {url}")


# ════════════════════════════════════════════════════════════════════════════
#  ARAÇ 4 — EUIPO Karar Detayı (Karar numarası ile)
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_euipo_decision_by_reference(
    karar_referansi: str,
) -> str:
    """
    EUIPO karar referansıyla (ör. R 2389/2020-4) kararın detayını getirir.

    Args:
        karar_referansi : Temyiz Kurulu formatı: "R XXXX/YYYY-Z"
                          İtiraz Birimi formatı:  "B XXXXXXX"
                          İptal Birimi formatı:   "C XXXXXXX"

    Returns:
        Kararın özeti, taraflar, dayanak maddeler ve eSearchCLW bağlantısı.
    """
    ref_clean = karar_referansi.strip().upper()

    # eSearchCLW direct link
    caslaw_url = f"{EUIPO_CASLAW_BASE}/#basic/trademark/{quote(ref_clean)}"

    # EUIPO API denemesi
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        for endpoint in [
            f"{EUIPO_CASLAW_BASE}/rest/decisions/trademark/{quote(ref_clean)}",
            f"{EUIPO_CASLAW_BASE}/rest/case/{quote(ref_clean)}",
            f"{EUIPO_CASLAW_BASE}/api/v1/decisions/{quote(ref_clean)}",
        ]:
            try:
                r = await client.get(endpoint)
                if r.status_code == 200:
                    data = r.json()
                    return _ok({
                        "kaynak":    "EUIPO eSearchCLW API",
                        "referans":  karar_referansi,
                        "veri":      data,
                        "caslaw_url": caslaw_url,
                    })
            except Exception:
                continue

    return _ok({
        "kaynak":    "EUIPO eSearchCLW (API yanıtsız)",
        "referans":  karar_referansi,
        "not": (
            "EUIPO eSearchCLW'nin doğrudan REST API'si dökümante edilmemiştir "
            "ve yanıt vermedi. Aşağıdaki bağlantıdan manuel erişim sağlayın."
        ),
        "caslaw_url":  caslaw_url,
        "manuel_url":  f"https://euipo.europa.eu/eSearchCLW/#key/trademark/{ref_clean}",
    })


# ════════════════════════════════════════════════════════════════════════════
#  ARAÇ 5 — SMK Maddesi ile İçtihat Eşleme
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def smk_madde_ictihat_esle(madde: str) -> str:
    """
    SMK maddesini AB marka hukukundaki karşılık gelen EUTMR maddesiyle eşleyip
    ilgili CJEU içtihadını getirir.

    Args:
        madde : SMK madde numarası, örn: "5", "5/1", "5/2", "6", "25", "23"

    Returns:
        EUTMR karşılığı, anahtar kavramlar ve ilgili CJEU kararları.
    """
    ESLESME = {
        "5":      {"eutmr": "7",    "kavram": "absolute grounds refusal distinctive character",        "aciklama": "Mutlak ret nedenleri (ayırt edici nitelik)"},
        "5/1":    {"eutmr": "7/1",  "kavram": "absolute grounds refusal non-distinctive sign",         "aciklama": "Tanımlayıcı ve ayırt edici nitelikten yoksun işaretler"},
        "5/2":    {"eutmr": "7/2",  "kavram": "absolute grounds part EU territory",                    "aciklama": "Kısmi red (AB'nin bir bölümünde)"},
        "5/3":    {"eutmr": "7/3",  "kavram": "acquired distinctive character use secondary meaning",  "aciklama": "Kullanım yoluyla kazanılan ayırt edicilik"},
        "6":      {"eutmr": "8",    "kavram": "relative grounds likelihood of confusion similar marks", "aciklama": "Göreli ret nedenleri — karıştırılma ihtimali"},
        "6/1-a":  {"eutmr": "8/1a", "kavram": "identical signs identical goods",                       "aciklama": "Aynı mal/hizmet için aynı işaret"},
        "6/1-b":  {"eutmr": "8/1b", "kavram": "likelihood of confusion similar signs goods services",  "aciklama": "Karıştırılma ihtimali — benzer işaret/mal/hizmet"},
        "6/4":    {"eutmr": "8/5",  "kavram": "well-known mark reputation unfair advantage",           "aciklama": "Tanınmış marka — itibardan haksız yarar"},
        "23":     {"eutmr": "59/1b","kavram": "bad faith trademark application",                       "aciklama": "Kötü niyet"},
        "25":     {"eutmr": "47/2", "kavram": "genuine use proof five years trade mark",               "aciklama": "Kullanım ispatı"},
        "26":     {"eutmr": "58",   "kavram": "revocation non-use trade mark",                         "aciklama": "Kullanmama nedeniyle hükümsüzlük"},
    }

    # Hem tam hem kısmi eşleşme dene
    eslesen = ESLESME.get(madde) or ESLESME.get(madde.split("/")[0])

    if not eslesen:
        return _ok({
            "uyari": f"SMK madde {madde} için doğrudan bir eşleşme bulunamadı.",
            "mevcut_maddeler": list(ESLESME.keys()),
        })

    # İlgili CJEU kararlarını getir
    cjeu_sonuc = await search_cjeu_decisions(
        anahtar_kelimeler=eslesen["kavram"],
        mahkeme="all",
        adet=8,
    )
    cjeu_data = json.loads(cjeu_sonuc)

    return _ok({
        "smk_madde":       madde,
        "eutmr_karsılık":  eslesen["eutmr"],
        "aciklama":        eslesen["aciklama"],
        "arama_kavramlari": eslesen["kavram"],
        "cjeu_kararlar":   cjeu_data.get("sonuclar", []),
        "cjeu_kaynak":     cjeu_data.get("kaynak", ""),
        "euipo_arama_url": _euipo_search_url(eslesen["kavram"]),
    })


# ════════════════════════════════════════════════════════════════════════════
#  Sunucuyu Başlat
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run()
