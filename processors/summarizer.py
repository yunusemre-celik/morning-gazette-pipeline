"""
Summarizer Module powered by Google Gemini API with Graceful Degradation.

Implements:
1. Google Gemini Flash with structured JSON output.
2. 3-step Exponential Backoff for 429/500 errors.
3. FallbackSummarizer for offline, missing-key, or emergency resilience scenarios.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import Settings, get_settings
from fetchers.base import AggregatedRawData, FinanceSummary
from processors.schema import (
    AIToolModel,
    GazetteContent,
    HeadlineStory,
    MarketInsight,
    TechStartupArticle,
)

logger = logging.getLogger("processors.summarizer")


TURKISH_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık"
}
TURKISH_DAYS = {
    0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe", 4: "Cuma", 5: "Cumartesi", 6: "Pazar"
}


def format_gazette_date(dt: Optional[datetime.datetime] = None) -> str:
    """Format datetime into standard Turkish newspaper dateline (e.g. '4 Ekim 2026, Pazar')."""
    if dt is None:
        dt = datetime.datetime.now()
    return f"{dt.day} {TURKISH_MONTHS.get(dt.month, '')} {dt.year}, {TURKISH_DAYS.get(dt.weekday(), '')}"


# Backward compatibility alias
format_turkish_date = format_gazette_date


class FallbackSummarizer:
    """
    Emergency rule-based summarizer.

    Activated when Gemini API key is missing or when all network/API retries fail.
    Guarantees zero-crash delivery of The Morning Gazette by synthesizing
    raw headlines, repositories, and financial data into the schema in Turkish.
    """

    @classmethod
    def synthesize(cls, raw_data: AggregatedRawData) -> GazetteContent:
        logger.info("Executing Emergency Fallback Summarizer (Offline / Graceful Mode)...")
        date_str = format_gazette_date()

        # 1. Headline Story: Pick highest score or first tech story
        stories = list(raw_data.tech_stories)
        if stories:
            top_story = max(stories, key=lambda s: s.score)
            stories.remove(top_story)
            headline = HeadlineStory(
                kicker="GÜNÜN MANŞETİ",
                title=top_story.title,
                lead_paragraph=(
                    f"{top_story.source} üzerinde en çok tartışılan bu kritik teknolojik gelişme, "
                    f"küresel yazılım ve girişimcilik ekosisteminde geniş yankı uyandırıyor."
                ),
                detailed_analysis=(
                    f"Topluluktan {top_story.score} puan ve {top_story.comments} yorum toplayan bu gelişme, "
                    f"sektör analistlerine göre ölçeklenebilirlik ve modern yazılım mimarilerinde "
                    f"önemli bir dönüşümün habercisi olarak değerlendiriliyor."
                ),
                source_name=top_story.source,
                source_url=top_story.url,
            )
        else:
            headline = HeadlineStory(
                kicker="GÜNÜN MANŞETİ",
                title="Yeni Nesil Otonom Sistemler Geliştirici Ekosisteminde Yükseliyor",
                lead_paragraph="Küresel açık kaynak topluluğu, otonom araçlar ve öncü yapay zeka ajanlarını hızla geliştirmeye devam ediyor.",
                detailed_analysis="Yazılım mimarileri, hafif ve modüler yerel modellere doğru köklü bir paradigma dönüşümü yaşıyor.",
                source_name="The Morning Gazette Editör Masası",
                source_url="https://github.com",
            )

        # 2. Tech & Startup Stories: 4-6 articles
        tech_articles: list[TechStartupArticle] = []
        for s in stories[:6]:
            summary_text = s.summary or f"{s.source} akışında {s.score} puan ve {s.comments} topluluk yorumu ile öne çıktı."
            tech_articles.append(
                TechStartupArticle(
                    category=s.source.upper(),
                    title=s.title,
                    summary=summary_text,
                    key_takeaway="Çevik mühendislik ekipleri için yeni mimari kalıplara ve operasyonel verimliliğe işaret ediyor.",
                    source_name=s.source,
                    source_url=s.url,
                )
            )

        # 3. AI Tools & Models: from GitHub repos & Hugging Face papers
        ai_tools: list[AIToolModel] = []
        for repo in raw_data.repositories[:3]:
            ai_tools.append(
                AIToolModel(
                    name=repo.name,
                    category="Açık Kaynak Deposu",
                    description=repo.description or "Geliştirici ekosisteminde trend olan açık kaynak yapay zeka aracı.",
                    why_it_matters=f"Geliştirici topluluğu tarafından {repo.stars:,} GitHub yıldızı ile destekleniyor.",
                    source_url=repo.html_url,
                )
            )

        for paper in raw_data.papers[:3]:
            ai_tools.append(
                AIToolModel(
                    name=paper.title,
                    category="Araştırma Makalesi / Model",
                    description=paper.summary or "Hugging Face üzerinde öne çıkan araştırma makalesi.",
                    why_it_matters=f"Öncü makine zekasını geliştirdiği için {paper.upvotes} topluluk oyu aldı.",
                    source_url=paper.url,
                )
            )

        # 4. Market Insight
        fx_rates = {f.base_currency: f.rate for f in raw_data.finance.fx_rates}
        usd_rate = fx_rates.get("USD", 0.0)
        eur_rate = fx_rates.get("EUR", 0.0)

        crypto_map = {c.symbol: c for c in raw_data.finance.crypto_prices}
        btc = crypto_map.get("BTC")
        eth = crypto_map.get("ETH")

        fx_desc = f"Dolar/TL {usd_rate:.2f} TL ve Euro/TL {eur_rate:.2f} TL seviyelerinde işlem görüyor." if usd_rate else "Döviz kurları yatay seyrediyor."
        crypto_desc = ""
        if btc:
            crypto_desc += f"Bitcoin ${btc.price_usd:,.0f} ({btc.change_24h:+.2f}%) seviyesinde "
        if eth:
            crypto_desc += f"ve Ethereum ${eth.price_usd:,.0f} ({eth.change_24h:+.2f}%) bandında hareket ediyor."

        market_insight = MarketInsight(
            market_summary="Küresel piyasalar, teknoloji devlerinin bilanço açıklamaları ve merkez bankası sinyalleri öncesinde dengeli bir momentum sergiliyor.",
            fx_commentary=fx_desc,
            crypto_commentary=crypto_desc or "Kripto varlık piyasaları temel teknik bantlar içerisinde konsolidasyonunu sürdürüyor.",
            editorial_take="Girişim kurucuları ve yöneticileri için sermaye verimliliği, kur riskini dengeleme ve nakit akışını koruma öncelikli kalmaya devam ediyor.",
        )

        return GazetteContent(
            edition_date=date_str,
            edition_number=f"Sayı {datetime.datetime.now().strftime('%y%j')}",
            headline=headline,
            tech_startup_stories=tech_articles,
            ai_tools=ai_tools,
            market_insight=market_insight,
            raw_finance=raw_data.finance,
            curator_note="Bu sayı The Morning Gazette Otonom Veri Hattı tarafından üretilmiştir.",
        )


class GeminiSummarizer:
    """
    Main AI Editorial Summarizer using Google Gemini API.

    Features:
    - Structured JSON generation via response_schema.
    - 3-step exponential backoff for transient 429/500 errors.
    - Automatic graceful degradation to FallbackSummarizer if unresolvable.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model = self.settings.GEMINI_MODEL or "gemini-3.8-flash"
        self.max_retries = max(1, self.settings.MAX_RETRIES)

    def _prepare_prompt(self, raw_data: AggregatedRawData) -> str:
        """Compose context payload for Gemini."""
        tech_context = [
            f"- [{s.source}] {s.title} (Score: {s.score}, Comments: {s.comments}) Link: {s.url}\n  Summary: {s.summary or ''}"
            for s in raw_data.tech_stories[:25]
        ]
        repo_context = [
            f"- [GitHub] {r.full_name}: {r.description} (Stars: {r.stars}) Link: {r.html_url}"
            for r in raw_data.repositories[:10]
        ]
        paper_context = [
            f"- [HuggingFace] {p.title}: {p.summary[:200]} (Upvotes: {p.upvotes}) Link: {p.url}"
            for p in raw_data.papers[:8]
        ]
        fx_context = [
            f"- {f.base_currency}/{f.target_currency}: {f.rate}"
            for f in raw_data.finance.fx_rates
        ]
        crypto_context = [
            f"- {c.name} ({c.symbol}): ${c.price_usd:,.2f} (24h: {c.change_24h:+.2f}%)"
            for c in raw_data.finance.crypto_prices
        ]

        return f"""
Sen saygın ve prestijli bir günlük teknoloji ve finans gazetesi olan 'The Morning Gazette'in Genel Yayın Yönetmenisin (Editor-in-Chief).
Teknoloji haberleri, açık kaynak projeler, yapay zeka araştırmaları ve finans piyasalarından toplanan aşağıdaki ham istihbaratı analiz et.
Üst düzey yöneticilere, mühendislere ve girişimcilere hitap eden, entelektüel derinliği yüksek, yapılandırılmış bir gazete bültenini TAMAMEN TÜRKÇE olarak hazırla.

### EDİTÖRYAL KURALLAR (EDITORIAL GUIDELINES):
1. 'headline' (Günün Manşeti): Küresel ölçekte en büyük etkiyi yaratan, dönüştürücü tek bir teknoloji konusunu manşete taşı. Çarpıcı bir Türkçe başlık (title), prestijli bir haber diliyle yazılmış giriş paragrafı (lead_paragraph) ve derinlemesine teknik/sektörel bir analiz (detailed_analysis) üret. 'kicker' alanına büyük harflerle Türkçe kategori etiketi yaz (Örn: "YAPAY ZEKA DEVRİMİ", "KÜRESEL TEKNOLOJİ", "YAZILIM MİMARİSİ").
2. 'tech_startup_stories': Girişim sermayesi ve teknoloji dünyasından 4 ila 6 adet yüksek sinyalli haberi seç ve derle. Her biri için akıcı bir Türkçe özet (summary) ve girişimcilere/mühendislere yönelik keskin bir stratejik çıkarım ('key_takeaway') yaz. 'category' alanını büyük harfle Türkçe yaz (Örn: "GİRİŞİM EKOSİSTEMİ", "SİBER GÜVENLİK", "BULUT MİMARİSİ").
3. 'ai_tools': GitHub ve Hugging Face akışından 3 ila 5 adet öne çıkan açık kaynak araç, kütüphane veya araştırma makalesini seç. Ne işe yaradığını (description) ve yazılım mühendisleri ile teknoloji liderleri için 'Neden Önemli' olduğunu ('why_it_matters') Türkçe olarak açıkla. 'category' alanını Türkçe yaz (Örn: "Açık Kaynak Araç", "Araştırma Makalesi", "Model").
4. 'market_insight': Makroekonomik görünümü (market_summary), döviz kurlarını (fx_commentary: Dolar/TL ve Euro/TL) ve kripto para piyasasını (crypto_commentary: BTC ve ETH) analiz et. Girişim kurucuları, CTO'lar ve yatırımcılar için taktiksel bir tavsiye ('editorial_take') ekle.
5. 'edition_date': Bugünün tarihini Türkçe biçimde yaz (Örn: '{format_gazette_date()}').

TÜM ÇIKTILAR, BAŞLIKLAR, METİNLER VE YORUMLAR AKICI VE PROFESYONEL BİR TÜRKÇE İLE OLMALIDIR.

### HAM VERİLER (RAW INGESTED DATA):
**Teknoloji ve Girişim Akışları:**
{chr(10).join(tech_context)}

**Açık Kaynak Kod Depoları (GitHub):**
{chr(10).join(repo_context)}

**Yapay Zeka Makaleleri ve Modeller (Hugging Face):**
{chr(10).join(paper_context)}

**Finansal Piyasalar (Döviz & Kripto):**
Döviz Kurları: {", ".join(fx_context) if fx_context else "Veri alınamadı"}
Kripto Varlıklar: {", ".join(crypto_context) if crypto_context else "Veri alınamadı"}
"""

    async def summarize(self, raw_data: AggregatedRawData) -> GazetteContent:
        """
        Produce structured GazetteContent using Gemini API with retry and fallback.
        """
        if not self.api_key or self.api_key in ("your_gemini_api_key_here", ""):
            logger.warning("GEMINI_API_KEY is not configured. Switching to FallbackSummarizer.")
            return FallbackSummarizer.synthesize(raw_data)

        prompt = self._prepare_prompt(raw_data)
        client = genai.Client(api_key=self.api_key)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GazetteContent,
            temperature=0.3,
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Sending structured synthesis request to Gemini (%s, attempt %d/%d)...",
                    self.model,
                    attempt,
                    self.max_retries,
                )

                # Execute synchronous client call in worker thread to prevent event loop blocking
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=self.model,
                    contents=prompt,
                    config=config,
                )

                if response and response.text:
                    parsed_json = json.loads(response.text)
                    content = GazetteContent.model_validate(parsed_json)
                    content.raw_finance = raw_data.finance
                    logger.info("Successfully synthesized Morning Gazette with Gemini!")
                    return content
                else:
                    raise ValueError("Gemini returned empty response.")

            except Exception as exc:
                is_transient = False
                error_str = str(exc)

                if isinstance(exc, APIError):
                    if exc.code in (429, 500, 503, 504):
                        is_transient = True
                elif "429" in error_str or "500" in error_str or "quota" in error_str.lower() or "timeout" in error_str.lower():
                    is_transient = True

                backoff_delay = 2 ** (attempt - 1)
                logger.warning(
                    "Gemini API attempt %d failed: %s. Transient=%s. Backoff: %ds",
                    attempt,
                    exc,
                    is_transient,
                    backoff_delay,
                )

                if attempt < self.max_retries and is_transient:
                    await asyncio.sleep(backoff_delay)
                elif attempt >= self.max_retries:
                    logger.error(
                        "All %d Gemini API retries exhausted. Activating Graceful FallbackSummarizer.",
                        self.max_retries,
                    )
                    break

        return FallbackSummarizer.synthesize(raw_data)
