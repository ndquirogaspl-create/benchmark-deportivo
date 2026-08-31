
# =============================================================================
# SCRAPER BENCHMARK COMPETITIVO - CSV AUTOMÁTICO (SIN CREDENCIALES)
# =============================================================================

import asyncio
import json
import os
import re
import csv
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# =============================================================================
# 1. CONFIGURACIÓN - URLs de las 17 tiendas
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

# Selectores CSS para extraer datos de cada sitio
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
    """Busca elementos en el HTML y extrae su texto."""
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
    """Extrae los textos alternativos de las imágenes de banners."""
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
    """Busca el monto de envío gratis en los textos extraídos."""
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
    """Detecta si hay descuento por suscripción a newsletter."""
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
    """Visita una URL y extrae toda la información."""

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

        # Cerrar cookies/pop-ups que bloquean el contenido
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

        # Esperar que aparezcan pop-ups de newsletter
        await page.wait_for_timeout(4000)

        # Leer el HTML de la página
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

        # Detectar pop-ups y newsletter
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
    """Ejecuta el scraper para las 17 tiendas."""

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
# 5. GUARDAR RESULTADOS EN CSV
# =============================================================================

def save_csv(results):
    """
    SIEMPRE genera el CSV, aunque no haya datos extraídos.
    Formato: Columnas = Retailers | Filas = Promociones, Financiación, Envío
    """

    print("\n📁 Generando archivos CSV...")

    # Crear carpeta SIEMPRE
    os.makedirs("resultados", exist_ok=True)

    mes = datetime.now().strftime("%B").upper()
    fecha = datetime.now().strftime("%Y-%m-%d")

    # --- Construir las filas ---
    headers = ["Meses"] + [r.nombre for r in results]

    # Fila 1: Promociones principales
    row_promos = [mes]
    for r in results:
        promos = []
        for alt in r.banners_alt_texts[:5]:
            promos.append(f"- {alt}")
        for promo in r.promociones[:5]:
            if promo not in r.banners_alt_texts:
                promos.append(f"- {promo}")
        cell = "\n".join(promos[:8]) if promos else "Sin datos detectados"
        if r.error:
            cell = f"ERROR: {r.error[:100]}"
        row_promos.append(cell)

    # Fila 2: Financiación
    row_financ = ["Financiación"]
    for r in results:
        financ = [f"- {t}" for t in r.financiacion_textos[:8]]
        cell = "\n".join(financ) if financ else "Sin datos detectados"
        row_financ.append(cell)

    # Fila 3: Envío
    row_envio = ["Envío"]
    for r in results:
        row_envio.append(r.envio_umbral)

    # --- Escribir CSV con fecha (historial) ---
    filename_dated = f"resultados/benchmark_{fecha}.csv"
    with open(filename_dated, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(row_promos)
        writer.writerow(row_financ)
        writer.writerow(row_envio)
    print(f"  ✓ CSV historial: {filename_dated}")

    # --- Escribir CSV "último" (se sobreescribe siempre) ---
    filename_latest = "resultados/benchmark_ultimo.csv"
    with open(filename_latest, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerow(row_promos)
        writer.writerow(row_financ)
        writer.writerow(row_envio)
    print(f"  ✓ CSV último:    {filename_latest}")

    # --- Verificar que los archivos existen ---
    for fname in [filename_dated, filename_latest]:
        if os.path.exists(fname):
            size = os.path.getsize(fname)
            print(f"  ✓ Verificado: {fname} ({size} bytes)")
        else:
            print(f"  ✗ ERROR: {fname} NO se creó")

    return filename_dated


# =============================================================================
# 6. GUARDAR BACKUP COMPLETO EN JSON
# =============================================================================

def save_json(results):
    """Guarda todos los datos extraídos en JSON (backup completo)."""

    os.makedirs("resultados", exist_ok=True)

    fecha = datetime.now().strftime("%Y-%m-%d")
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
            "envio_textos": r.envio_textos,
            "popup": r.popups_detectados,
            "popup_textos": r.popup_textos,
            "newsletter": r.newsletter_detectado,
            "newsletter_descuento": r.newsletter_descuento,
            "error": r.error,
        })

    filename = f"resultados/benchmark_{fecha}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    if os.path.exists(filename):
        size = os.path.getsize(filename)
        print(f"  ✓ JSON guardado: {filename} ({size} bytes)")
    else:
        print(f"  ✗ ERROR: {filename} NO se creó")


# =============================================================================
# 7. EJECUCIÓN PRINCIPAL
# =============================================================================

async def main():
    print("\n🚀 Iniciando benchmark competitivo...\n")

    # 1. Ejecutar scraping de las 17 URLs
    results = await run_scraper()

    # 2. Guardar CSV (formato para Google Sheets)
    save_csv(results)

    # 3. Guardar JSON (backup completo)
    save_json(results)

    # 4. Resumen final
    print("\n" + "=" * 60)
    print("📊 RESUMEN DE EXTRACCIÓN")
    print("=" * 60)
    for r in results:
        status = "✓" if not r.error else "✗"
        print(f"  {status} {r.nombre}: "
              f"{len(r.promociones)} promos, "
              f"{len(r.banners_alt_texts)} banners, "
              f"{len(r.financiacion_textos)} financ, "
              f"envío: {r.envio_umbral}")
    print("=" * 60)

    # 5. Verificar archivos generados
    print("\n📁 Archivos en resultados/:")
    if os.path.exists("resultados"):
        for f in os.listdir("resultados"):
            filepath = os.path.join("resultados", f)
            size = os.path.getsize(filepath)
            print(f"  → {f} ({size} bytes)")
    else:
        print("  ✗ La carpeta resultados/ NO existe")

    print("\n🏁 Benchmark completado")


if __name__ == "__main__":
    asyncio.run(main())

