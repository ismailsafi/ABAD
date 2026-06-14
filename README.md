# EUIPO & ABAD (CJEU) İçtihat MCP Sunucusu

SMK 6769 sayılı Kanun kapsamında dilekçe hazırlamak için EUIPO ve AB mahkemesi  
içtihadına erişim sağlayan FastMCP sunucusu.

## Araçlar

| Araç | Açıklama |
|------|----------|
| `search_euipo_decisions` | EUIPO Temyiz Kurulu / İtiraz Birimi kararları |
| `search_cjeu_decisions` | ABAD ve Genel Mahkeme kararları (EUR-Lex CELLAR) |
| `get_cjeu_decision_text` | ECLI veya CELEX ile tam karar metni |
| `get_euipo_decision_by_reference` | Referans numarasıyla EUIPO kararı |
| `smk_madde_ictihat_esle` | SMK maddesi → EUTMR karşılığı + CJEU içtihadı |

## Veri Kaynakları

- **EUIPO eSearchCLW** `https://euipo.europa.eu/eSearchCLW/`  
  Temyiz Kurulu, İtiraz Birimi, İptal Birimi kararları + Genel Mahkeme / ABAD hükümleri.  
  ⚠️ Resmi REST API dökümantasyonu yayımlanmamıştır; sunucu undocumented endpoint'leri dener.

- **EUR-Lex CELLAR SPARQL** `https://publications.europa.eu/webapi/rdf/sparql`  
  AB'nin resmi açık veri kaynağı. Kimlik doğrulama gerektirmez.

## Kurulum

```bash
pip install -r requirements.txt
```

## Çalıştırma

### Lokal test (stdio):
```bash
python main.py
```

### Uzak MCP sunucusu (SSE — Claude.ai ile uyumlu):
```bash
fastmcp run main.py --transport sse --host 0.0.0.0 --port 8000
```

### Railway / Render deployment:
```
Procfile:  web: fastmcp run main.py --transport sse --host 0.0.0.0 --port $PORT
```

## Claude.ai'ya Ekleme

Settings → Integrations → Add MCP Server:
```
URL: https://YOUR-DEPLOYMENT-URL/sse
```

## SMK ↔ EUTMR Madde Eşleşme Tablosu

| SMK Maddesi | EUTMR Karşılığı | Konu |
|-------------|-----------------|------|
| 5           | 7               | Mutlak ret nedenleri |
| 5/3         | 7/3             | Kullanımla kazanılan ayırt edicilik |
| 6 / 6/1-b   | 8/1-b           | Karıştırılma ihtimali |
| 6/4         | 8/5             | Tanınmış marka |
| 23          | 59/1-b          | Kötü niyet |
| 25          | 47/2            | Kullanım ispatı |
| 26          | 58              | Kullanmama nedeniyle hükümsüzlük |
