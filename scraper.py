
# =============================================================================
# SCRAPER BENCHMARK COMPETITIVO - EXTRACCIÓN INTELIGENTE DE TEXTO COMPLETO
# =============================================================================
# En vez de depender de selectores CSS específicos por sitio,
# este scraper extrae TODO el texto visible de cada página
# y lo clasifica automáticamente por categoría usando patrones.
# =============================================================================

import asyncio
import json
import os
import re
import csv
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
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


# =============================================================================
# 2. PATRONES DE CLASIFICACIÓN
# =============================================================================
# Estos patrones buscan palabras clave en el texto para clasificarlo
# en las categorías del benchmark.

PATTERNS = {
    "promociones": [
        r'(?i).*(?:off|dto|descuento|sale|liquidaci[oó]n|outlet|promo|rebaja|oferta|hot\s*sale|cyber|black\s*friday|especial|imperdible|últim[oa]s?\s*unidades|nuevo|lanzamiento|colección|temporada|invierno|verano|otoño|primavera).*',
    ],
    "financiacion": [
        r'(?i).*(?:cuota|sin\s*inter[eé]s|inter[eé]s|financ|tarjeta|visa|master|amex|american\s*express|naranja|cabal|cordobesa|nativa|mercado\s*pago|modo|banco|bbva|galicia|santander|macro|naci[oó]n|provincia|ciudad|hsbc|icbc|patagonia|brubank|uala|ual[aá]|personal\s*pay|cuenta\s*dni|ahora\s*\d+|plan\s*z|go\s*cuotas|bancarizad).*',
    ],
    "envio": [
        r'(?i).*(?:env[ií]o\s*(?:gratis|gr[aá]tis|free)|free\s*shipping|retir[oaáe]\s*(?:gratis|en\s*(?:tienda|sucursal|local))|pick\s*up|despacho|entrega|shipping|costo\s*de\s*env[ií]o|env[ií]o\s*a\s*todo|env[ií]o\s*sin\s*cargo|\$[\d.,]+.*env[ií]o|env[ií]o.*\$[\d.,]+).*',
    ],
    "newsletter": [
        r'(?i).*(?:newsletter|suscrib[ií]|registr[aá]te|reg[ií]strate|dejanos\s*tu\s*(?:mail|email|correo)|recib[ií]\s*(?:ofertas|novedades|promos)|primera\s*compra|bienvenida|welcome|10%|15%|20%\s*(?:off|dto|descuento)|código\s*de\s*descuento|cup[oó]n).*',
    ],
    "fidelizacion": [
        r'(?i).*(?:programa\s*de\s*(?:fidelizaci[oó]n|lealtad|puntos|beneficios)|loyalty|puntos|rewards|miembr[oa]|member|club|adi\s*club|nike\s*member|puma\s*member|vip|premium\s*member|acumul[aá]\s*puntos|canje|beneficio\s*exclusiv).*',
    ],
    "retiro": [
        r'(?i).*(?:retir[oaáe]\s*(?:en\s*(?:tienda|sucursal|local|punto)|gratis|sin\s*cargo)|pick\s*up|click\s*(?:and|&)\s*collect|recog[eé]\s*en|buscar\s*en\s*(?:tienda|sucursal|local)|punto\s*de\s*retiro|sucursal(?:es)?\s*(?:disponibles|\d+)).*',
    ],
    "popup": [
        r'(?i).*(?:popup|pop-up|modal|suscrib|newsletter|no\s*te\s*(?:pierdas|vayas)|antes\s*de\s*irte|espera|wait|exit|cerrar|close\s*this).*',
    ],
}

# Palabras a IGNORAR (menú de navegación, footer, etc.)
IGNORE_PATTERNS = [
    r'(?i)^(?:inicio|home|contacto|nosotros|quienes\s*somos|preguntas\s*frecuentes|faq|términos|condiciones|privacidad|política|mapa\s*del\s*sitio|sitemap|copyright|©|todos\s*los\s*derechos|seguinos|síguenos|facebook|instagram|twitter|youtube|tiktok|whatsapp|linkedin)$',
    r'(?i)^(?:hombre|mujer|niños|niñas|accesorios|calzado|ropa|indumentaria|zapatillas|botines|running|training|fútbol|básquet|tenis|outdoor)$',
    r'^.{0,4}$',  # Textos muy cortos (menos de 5 caracteres)
    r'^.{500,}$',  # Textos muy largos (más de 500 caracteres, probablemente basura)
]


# =============================================================================
# 3. MODELO DE DATOS
# =============================================================================

@dataclass
class RetailerData:
    nombre: str
    url: str
    fecha_scraping: str = ""
    mes: str = ""
    # Datos clasificados
    promociones: list = field(default_factory=list)
    financiacion: list = field(default_factory=list)
    envio: list = field(default_factory=list)
    envio_umbral: str = "No detectado"
    newsletter: list = field(default_factory=list)
    fidelizacion: list = field(default_factory=list)
    retiro: list = field(default_factory=list)
    popup: list = field(default_factory=list)
    # Banners (alt text de imágenes)
    banners: list = field(default_factory=list)
    # Metadata
    total_textos_extraidos: int = 0
    error: Optional[str] = None


# =============================================================================
# 4. FUNCIONES DE EXTRACCIÓN Y CLASIFICACIÓN
# =============================================================================

def should_ignore(text):
    """Verifica si un texto debe ser ignorado (navegación, footer, etc.)."""
    for pattern in IGNORE_PATTERNS:
        if re.match(pattern, text.strip()):
            return True
    return False


def classify_text(text):
    """
    Clasifica un texto en una o más categorías del benchmark.
    Retorna una lista de categorías donde encaja.
    """
    categories = []
    for category, patterns in PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, text):
                categories.append(category)
                break  # Una vez que matchea, no seguir con más patrones de la misma categoría
    return categories


def extract_shipping_amount(texts):
    """Extrae el monto de envío gratis de los textos clasificados como envío."""
    patterns = [
        r'\$\s*[\d.,]+',
        r'[\d.,]+\s*(?:pesos|\$)',
        r'(?:desde|a\s*partir\s*de|superando|compras?\s*(?:de|desde|mayores?\s*a?))\s*\$?\s*([\d.,]+)',
    ]
    for text in texts:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()
    
    # Si dice "envío gratis" sin monto
    for text in texts:
        if re.search(r'(?i)env[ií]o\s*(?:gratis|sin\s*cargo)', text):
            return "Envío gratis (sin monto mínimo detectado)"
    
    return "No detectado"


def clean_text(text):
    """Limpia un texto extraído."""
    # Remover espacios múltiples
    text = re.sub(r'\s+', ' ', text).strip()
    # Remover caracteres especiales sueltos
    text = re.sub(r'^[\s\-\•\·\|\>\<]+', '', text).strip()
    return text


# =============================================================================
# 5. SCRAPER PRINCIPAL
# =============================================================================

async def scrape_retailer(page, nombre, url):
    """Visita una URL, extrae TODO el texto visible y lo clasifica."""

    data = RetailerData(
        nombre=nombre,
        url=url,
        fecha_scraping=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        mes=datetime.now().strftime("%B %Y").upper(),
    )

    try:
        print(f"\n  → Scrapeando {nombre}...")
        
        # Navegar al sitio
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # Esperar carga dinámica
        await page.wait_for_timeout(6000)

        # Cerrar cookies/pop-ups que bloquean el contenido
        for sel in [
            "button:has-text('Aceptar')",
            "button:has-text('Cerrar')",
            "button:has-text('Entendido')",
            "button:has-text('OK')",
            "button:has-text('Continuar')",
            "[class*='cookie'] button",
            "[class*='accept'] button",
            "[class*='close']",
            "[aria-label='Close']",
            "[aria-label='Cerrar']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    await page.wait_for_timeout(500)
            except Exception:
                continue

        # Esperar pop-ups de newsletter (suelen aparecer tras unos segundos)
        await page.wait_for_timeout(5000)

        # Scroll para cargar contenido lazy
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await page.wait_for_timeout(2000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        await page.wait_for_timeout(2000)

        # =====================================================
        # ESTRATEGIA 1: Extraer TODO el texto visible
        # =====================================================
        all_texts = await page.evaluate("""
            () => {
                const texts = [];
                const seen = new Set();
                
                // Recorrer todos los elementos visibles
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_ELEMENT,
                    null,
                    false
                );
                
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    const style = window.getComputedStyle(el);
                    
                    // Saltar elementos ocultos
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                        continue;
                    }
                    
                    // Obtener texto directo del elemento (no de hijos)
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === Node.TEXT_NODE)
                        .map(n => n.textContent.trim())
                        .join(' ')
                        .trim();
                    
                    if (directText && directText.length > 4 && !seen.has(directText)) {
                        seen.add(directText);
                        texts.push(directText);
                    }
                    
                    // También capturar texto completo de elementos pequeños (botones, badges, etc.)
                    if (el.children.length === 0 || ['A', 'BUTTON', 'SPAN', 'STRONG', 'B', 'EM', 'H1', 'H2', 'H3', 'H4', 'P', 'LI', 'LABEL'].includes(el.tagName)) {
                        const fullText = el.textContent.trim();
                        if (fullText && fullText.length > 4 && fullText.length < 500 && !seen.has(fullText)) {
                            seen.add(fullText);
                            texts.push(fullText);
                        }
                    }
                }
                
                return texts;
            }
        """)

        # =====================================================
        # ESTRATEGIA 2: Extraer alt text de imágenes (banners)
        # =====================================================
        banner_texts = await page.evaluate("""
            () => {
                const alts = [];
                const seen = new Set();
                document.querySelectorAll('img').forEach(img => {
                    const alt = (img.alt || '').trim();
                    if (alt && alt.length > 4 && !seen.has(alt)) {
                        seen.add(alt);
                        alts.push(alt);
                    }
                });
                return alts;
            }
        """)

        # =====================================================
        # ESTRATEGIA 3: Detectar pop-ups/modales activos
        # =====================================================
        popup_texts = await page.evaluate("""
            () => {
                const texts = [];
                const seen = new Set();
                const selectors = [
                    '[class*="popup"]', '[class*="modal"]', '[class*="newsletter"]',
                    '[class*="overlay"]', '[class*="lightbox"]', '[id*="popup"]',
                    '[id*="modal"]', '[id*="newsletter"]', '[role="dialog"]',
                    '[class*="exit"]', '[class*="subscribe"]'
                ];
                
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden') {
                            const text = el.textContent.trim();
                            if (text && text.length > 10 && text.length < 1000 && !seen.has(text)) {
                                seen.add(text);
                                texts.push(text);
                            }
                        }
                    });
                });
                
                return texts;
            }
        """)

        # =====================================================
        # CLASIFICAR TODOS LOS TEXTOS
        # =====================================================
        
        # Combinar todas las fuentes
        all_extracted = all_texts + banner_texts + popup_texts
        data.total_textos_extraidos = len(all_extracted)
        data.banners = banner_texts[:15]  # Guardar top 15 banners

        # Clasificar cada texto
        for raw_text in all_extracted:
            text = clean_text(raw_text)
            
            if not text or should_ignore(text):
                continue
            
            categories = classify_text(text)
            
            for cat in categories:
                target_list = getattr(data, cat)
                if text not in target_list and len(target_list) < 15:  # Máximo 15 por categoría
                    target_list.append(text)

        # Extraer monto de envío
        data.envio_umbral = extract_shipping_amount(data.envio)

        # Resumen
        print(f"  ✓ {nombre}: "
              f"{data.total_textos_extraidos} textos extraídos → "
              f"{len(data.promociones)} promos, "
              f"{len(data.financiacion)} financ, "
              f"{len(data.envio)} envío ({data.envio_umbral}), "
              f"{len(data.newsletter)} newsletter, "
              f"{len(data.fidelizacion)} fideliz, "
              f"{len(data.retiro)} retiro, "
              f"{len(data.banners)} banners")

    except Exception as e:
        data.error = str(e)
        print(f"  ✗ Error en {nombre}: {e}")

    return data


async def run_scraper():
    """Ejecuta el scraper para las 17 tiendas."""

    print("=" * 70)
    print(f"  BENCHMARK COMPETITIVO - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Método: Extracción de texto completo + clasificación inteligente")
    print("=" * 70)

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="es-AR",
        )
        page = await context.new_page()

        for nombre, url in RETAILERS.items():
            data = await scrape_retailer(page, nombre, url)
            results.append(data)

        await browser.close()

    print(f"\n{'=' * 70}")
    print(f"  ✅ Scraping completado: {len(results)} retailers")
    print(f"{'=' * 70}")
    return results


# =============================================================================
# 6. GUARDAR RESULTADOS EN CSV
# =============================================================================

def save_csv(results):
    """
    Genera el CSV con el formato:
    Columnas = Retailers | Filas = Mes (promos), Financiación, Envío, Newsletter, Fidelización, Retiro
    """

    print("\n📁 Generando archivos CSV...")
    os.makedirs("resultados", exist_ok=True)

    mes = datetime.now().strftime("%B").upper()
    fecha = datetime.now().strftime("%Y-%m-%d")

    headers = ["Meses"] + [r.nombre for r in results]

    # --- Fila 1: Promociones del mes ---
    row_promos = [mes]
    for r in results:
        items = []
        for b in r.banners[:5]:
            items.append(f"- {b}")
        for p in r.promociones[:5]:
            if p not in r.banners:
                items.append(f"- {p}")
        cell = "\n".join(items[:10]) if items else "Sin datos detectados"
        if r.error:
            cell = f"ERROR: {r.error[:80]}"
        row_promos.append(cell)

    # --- Fila 2: Financiación ---
    row_financ = ["Financiación"]
    for r in results:
        items = [f"- {t}" for t in r.financiacion[:10]]
        row_financ.append("\n".join(items) if items else "Sin datos detectados")

    # --- Fila 3: Envío ---
    row_envio = ["Envío"]
    for r in results:
        if r.envio:
            envio_info = r.envio_umbral
            detalles = [t for t in r.envio[:3] if t != r.envio_umbral]
            if detalles:
                envio_info += "\n" + "\n".join(f"- {d}" for d in detalles)
            row_envio.append(envio_info)
        else:
            row_envio.append(r.envio_umbral)

    # --- Fila 4: Newsletter ---
    row_news = ["Newsletter"]
    for r in results:
        items = [f"- {t}" for t in r.newsletter[:5]]
        row_news.append("\n".join(items) if items else "No detectado")

    # --- Fila 5: Programa de Fidelización ---
    row_fidel = ["Programa de Fidelización"]
    for r in results:
        items = [f"- {t}" for t in r.fidelizacion[:5]]
        row_fidel.append("\n".join(items) if items else "No detectado")

    # --- Fila 6: Opciones de Retiro ---
    row_retiro = ["Opciones de Retiro"]
    for r in results:
        items = [f"- {t}" for t in r.retiro[:5]]
        row_retiro.append("\n".join(items) if items else "No detectado")

    # --- Escribir CSVs ---
    all_rows = [headers, row_promos, row_financ, row_envio, row_news, row_fidel, row_retiro]

    for filename in [f"resultados/benchmark_{fecha}.csv", "resultados/benchmark_ultimo.csv"]:
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            for row in all_rows:
                writer.writerow(row)
        size = os.path.getsize(filename)
        print(f"  ✓ {filename} ({size:,} bytes)")

    return f"resultados/benchmark_{fecha}.csv"


# =============================================================================
# 7. GUARDAR BACKUP COMPLETO EN JSON
# =============================================================================

def save_json(results):
    """Guarda todos los datos extraídos en JSON."""

    os.makedirs("resultados", exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d")

    export = []
    for r in results:
        export.append({
            "retailer": r.nombre,
            "url": r.url,
            "fecha": r.fecha_scraping,
            "mes": r.mes,
            "total_textos": r.total_textos_extraidos,
            "promociones": r.promociones,
            "banners": r.banners,
            "financiacion": r.financiacion,
            "envio": r.envio,
            "envio_umbral": r.envio_umbral,
            "newsletter": r.newsletter,
            "fidelizacion": r.fidelizacion,
            "retiro": r.retiro,
            "popup": r.popup,
            "error": r.error,
        })

    filename = f"resultados/benchmark_{fecha}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    size = os.path.getsize(filename)
    print(f"  ✓ {filename} ({size:,} bytes)")


# =============================================================================
# 8. EJECUCIÓN PRINCIPAL
# =============================================================================

async def main():
    print("\n🚀 Iniciando benchmark competitivo (Extracción Inteligente)...\n")

    # 1. Scraping
    results = await run_scraper()

    # 2. CSV
    save_csv(results)

    # 3. JSON
    save_json(results)

    # 4. Resumen
    print("\n" + "=" * 70)
    print("  📊 RESUMEN DE EXTRACCIÓN")
    print("=" * 70)
    print(f"  {'Retailer':<20} {'Textos':>7} {'Promos':>7} {'Financ':>7} {'Envío':>7} {'News':>6} {'Fidel':>6} {'Retiro':>7}")
    print("  " + "-" * 68)
    for r in results:
        status = "✓" if not r.error else "✗"
        print(f"  {status} {r.nombre:<18} {r.total_textos_extraidos:>7} {len(r.promociones):>7} "
              f"{len(r.financiacion):>7} {len(r.envio):>7} {len(r.newsletter):>6} "
              f"{len(r.fidelizacion):>6} {len(r.retiro):>7}")
    print("=" * 70)

    # 5. Verificar archivos
    print("\n📁 Archivos generados:")
    if os.path.exists("resultados"):
        for f in sorted(os.listdir("resultados")):
            size = os.path.getsize(os.path.join("resultados", f))
            print(f"  → {f} ({size:,} bytes)")

    print("\n🏁 Benchmark completado exitosamente")


if __name__ == "__main__":
    asyncio.run(main())

