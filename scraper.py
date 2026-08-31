
# =============================================================================
# SCRAPER BENCHMARK COMPETITIVO - GITHUB ACTIONS + GOOGLE SHEETS
# =============================================================================

import asyncio
import json
import os
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials

# =============================================================================
# 1. CONFIGURACIÓN
# =============================================================================

RETAILERS = {
    "Sporting": "https://www.sporting.com.ar/",
    "Solo Deportes": "https://www.solodeportes.com.ar/",
    "Dexter": "https://www.dexter.com.ar/",
    "Stock Center": "https://www.stockcenter.com.ar/home",
    "Open Sports": "https://www.opensports.com.ar/",
    "Punto Deportivo": "https://www.puntodeportivo.com.ar/",
    "Seven Sport": "https://www.sevensport.com.ar/",
    "Moov": "https://www.moov.com.ar/",
    "Grid": "https://www.grid.com.ar/",
    "Adidas": "https://www.adidas.com.ar/",
    "Topper": "https://www.topper.com.ar/",
    "Puma": "https://ar.puma.com/",
    "Under Armour": "https://www.underarmour.com.ar/",
    "On Sports": "https://www.onsports.com.ar/",
    "Nike": "https://www.nike.com.ar/",
    "Digital Sport": "https://www.digitalsport.com.ar/",
    "Newsport": "https://www.newsport.com.ar/",
}

# Google Sheets config (desde variables de entorno)
SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1Yl1pZTU4lY67fvzu5HJoocBNPKc28A5fr72KfzuWL-A"
)
SHEET_NAME = os.environ.get("SHEET_NAME", "Benchmark IA")

# Selectores CSS por tipo de dato
# ⚠️ IMPORTANTE: Ajustar estos selectores inspeccionando el HTML real de cada sitio
SELECTORS = {
    "banners": [
        ".slick-slide img",
        ".carousel-item img",
        ".swiper-slide img",
        ".banner img",
        ".hero-banner img",
        "[class*='banner'] img",
        "[class*='carousel'] img",
        "[class*='slider'] img",
        "[class*='swiper'] img",
        ".vtex-store-components img",
        "[class*='hero'] img",
        "picture img",
        "[data-testid*='banner'] img",
        "[data-testid*='carousel'] img",
    ],
    "promotions": [
        "[class*='promo']",
        "[class*='offer']",
        "[class*='discount']",
        "[class*='sale']",
        "[class*='cuota']",
        "[class*='envio']",
        "[class*='shipping']",
        "[class*='free-shipping']",
        "[class*='installment']",
        "[class*='destacad']",
        "[class*='oferta']",
        ".vtex-store-components-3-x-infoCardContainer",
    ],
    "popups": [
        "[class*='popup']",
        "[class*='modal']",
        "[class*='newsletter']",
        "[class*='overlay']",
        "[class*='lightbox']",
        "[class*='exit-intent']",
        "[id*='popup']",
        "[id*='modal']",
        "[id*='newsletter']",
    ],
    "shipping": [
        "[class*='shipping']",
        "[class*='envio']",
        "[class*='envío']",
        "[class*='free-shipping']",
        "[class*='delivery']",
        "[class*='freeShipping']",
    ],
    "financing": [
        "[class*='cuota']",
        "[class*='installment']",
        "[class*='payment']",
        "[class*='financ']",
        "[class*='banco']",
        "[class*='bank']",
        "[class*='tarjeta']",
        "[class*='card']",
        "[class*='interest']",
    ],
}


# =============================================================================
# 2. MODELO DE DATOS
# =============================================================================

@dataclass
class RetailerData:
    nombre: str
    url: str
    fecha_scraping: str = ""
    mes: str = ""
    promociones: list = field(default_factory=list)
    banners_alt_texts: list = field(default_factory=list)
    financiacion_textos: list = field(default_factory=list)
    envio_textos: list = field(default_factory=list)
    envio_umbral: str = "No detectado"
    popups_detectados: bool = False
    popup_textos: list = field(default_factory=list)
    newsletter_detectado: bool = False
    newsletter_descuento: str = "No detectado"
    error: Optional[str] = None


# =============================================================================
# 3. FUNCIONES DE EXTRACCIÓN
# =============================================================================

def extract_text_from_elements(soup, selectors):
    texts = []
    for selector in selectors:
        try:
            for el in soup.select(selector):
                text = el.get_text(strip=True)
                if text and len(text) > 5 and text not in texts:
                    texts.append(text)
        except Exception:
            continue
    return texts


def extract_banner_info(soup):
    alt_texts = []
    for selector in SELECTORS["banners"]:
        try:
            for img in soup.select(selector):
                alt = img.get("alt", "").strip()
                if alt and len(alt) > 3 and alt not in alt_texts:
                    alt_texts.append(alt)
        except Exception:
            continue
    return alt_texts


def extract_shipping_threshold(texts):
    patterns = [
        r'\$[\d.,]+',
        r'envío\s*gratis\s*(?:desde|a partir de)?\s*\$?[\d.,]+',
        r'gratis.*?\$([\d.,]+)',
        r'\$([\d.,]+).*?gratis',
    ]
    for text in texts:
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["envío", "envio", "shipping", "gratis"]):
            for pattern in patterns:
                match = re.search(pattern, text_lower)
                if match:
                    return match.group(0).strip()
    return "No detectado"


def detect_newsletter_discount(popup_texts):
    patterns = [
        r'(\d+)\s*%\s*(?:off|dto|descuento|de descuento)',
        r'descuento\s*(?:del?)?\s*(\d+)\s*%',
        r'(\d+)\s*%\s*en tu primera compra',
    ]
    for text in popup_texts:
        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                return f"{match.group(1)}% descuento"
    return "No detectado"


# =============================================================================
# 4. SCRAPER PRINCIPAL
# =============================================================================

async def scrape_retailer(page, nombre, url):
    data = RetailerData(
        nombre=nombre,
        url=url,
        fecha_scraping=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        mes=datetime.now().strftime("%B %Y").upper(),
    )

    try:
        print(f"  → Scrapeando {nombre}...")
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(5000)

        # Cerrar cookies/pop-ups iniciales
        for sel in [
            "button:has-text('Aceptar')",
            "button:has-text('Cerrar')",
            "[class*='cookie'] button",
            "[class*='accept']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                continue

        # Esperar pop-ups de newsletter
        await page.wait_for_timeout(4000)

        # Parsear HTML
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Extraer datos
        data.banners_alt_texts = extract_banner_info(soup)
        data.promociones = extract_text_from_elements(soup, SELECTORS["promotions"])
        data.financiacion_textos = extract_text_from_elements(soup, SELECTORS["financing"])
        data.envio_textos = extract_text_from_elements(soup, SELECTORS["shipping"])
        data.envio_umbral = extract_shipping_threshold(
            data.envio_textos + data.promociones + data.banners_alt_texts
        )

        # Pop-ups / Newsletter
        for selector in SELECTORS["popups"]:
            try:
                for el in soup.select(selector):
                    text = el.get_text(strip=True)
                    if text and len(text) > 5:
                        data.popups_detectados = True
                        data.popup_textos.append(text)
                        if any(kw in text.lower() for kw in ["newsletter", "suscri", "email"]):
                            data.newsletter_detectado = True
            except Exception:
                continue

        if data.popup_textos:
            data.newsletter_descuento = detect_newsletter_discount(data.popup_textos)

        print(f"  ✓ {nombre}: {len(data.promociones)} promos, "
              f"{len(data.banners_alt_texts)} banners, envío: {data.envio_umbral}")

    except Exception as e:
        data.error = str(e)
        print(f"  ✗ Error en {nombre}: {e}")

    return data


async def run_scraper():
    print("=" * 60)
    print(f"BENCHMARK COMPETITIVO - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
        )
        page = await context.new_page()

        for nombre, url in RETAILERS.items():
            data = await scrape_retailer(page, nombre, url)
            results.append(data)

        await browser.close()

    print(f"\n✅ Scraping completado: {len(results)} retailers")
    return results


# =============================================================================
# 5. FORMATEO → GOOGLE SHEETS (tu formato)
# =============================================================================

def format_results(results):
    """
    Formato solicitado:
    Fila 1: Encabezado (Meses | Retailer1 | Retailer2 | ...)
    Fila 2: MES → Promociones principales (bullets)
    Fila 3: Financiación → Institucional + bancaria (bullets)
    Fila 4: Envío → Monto umbral
    """

    mes = datetime.now().strftime("%B").upper()
    headers = ["Meses"] + [r.nombre for r in results]

    # Fila promociones
    row_promos = [mes]
    for r in results:
        promos = []
        for alt in r.banners_alt_texts[:5]:
            promos.append(f"- {alt}")
        for promo in r.promociones[:5]:
            if promo not in r.banners_alt_texts:
                promos.append(f"- {promo}")
        row_promos.append("\n".join(promos[:8]) if promos else "No detectado")

    # Fila financiación
    row_financ = ["Financiación"]
    for r in results:
        financ = [f"- {t}" for t in r.financiacion_textos[:8]]
        row_financ.append("\n".join(financ) if financ else "No detectado")

    # Fila envío
    row_envio = ["Envío"]
    for r in results:
        row_envio.append(r.envio_umbral)

    return [headers, row_promos, row_financ, row_envio]


# =============================================================================
# 6. UPLOAD A GOOGLE SHEETS
# =============================================================================

def upload_to_sheets(data_rows):
    """Sube los datos formateados a Google Sheets."""

    print("\n📊 Subiendo datos a Google Sheets...")

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # Buscar o crear la hoja
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=10, cols=20)

    # Verificar si ya hay datos del mismo mes (para agregar filas, no sobreescribir)
    existing = worksheet.get_all_values()

    if len(existing) <= 1:
        # Hoja vacía o solo encabezado → escribir todo
        worksheet.clear()
        worksheet.update("A1", data_rows, value_input_option="RAW")
        print(f"  ✓ Datos escritos desde cero ({len(data_rows)} filas)")
    else:
        # Ya hay datos → agregar las 3 filas de datos debajo (sin repetir header)
        next_row = len(existing) + 2  # +2 para dejar una fila vacía de separación
        cell_range = f"A{next_row}"
        worksheet.update(cell_range, data_rows[1:], value_input_option="RAW")
        print(f"  ✓ Datos agregados desde fila {next_row}")

    print(f"  ✓ Google Sheets actualizado: {SHEET_NAME}")


# =============================================================================
# 7. BACKUP LOCAL (JSON)
# =============================================================================

def save_backup(results):
    export = []
    for r in results:
        export.append({
            "retailer": r.nombre,
            "url": r.url,
            "fecha": r.fecha_scraping,
            "mes": r.mes,
            "promociones": r.promociones,
            "banners": r.banners_alt_texts,
            "financiacion": r.financiacion_textos,
            "envio_umbral": r.envio_umbral,
            "popup": r.popups_detectados,
            "newsletter": r.newsletter_detectado,
            "newsletter_descuento": r.newsletter_descuento,
            "error": r.error,
        })

    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print("💾 Backup guardado: benchmark_results.json")


# =============================================================================
# 8. MAIN
# =============================================================================

async def main():
    # 1. Scraping
    results = await run_scraper()

    # 2. Formatear para Sheets
    data_rows = format_results(results)

    # 3. Subir a Google Sheets
    try:
        upload_to_sheets(data_rows)
    except Exception as e:
        print(f"⚠️ Error subiendo a Sheets: {e}")
        print("   Los datos se guardarán solo en backup local")

    # 4. Backup local
    save_backup(results)

    print("\n🏁 Benchmark completado exitosamente")


if __name__ == "__main__":
    asyncio.run(main())

