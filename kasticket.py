"""Kasticket-demo: foto van een kasticket -> gestructureerde data -> controle.

Gebruik:
    python kasticket.py tickets/colruyt.jpg

Werkwijze:
    1. De foto gaat naar Claude (multimodaal model).
    2. Claude geeft gestructureerde data terug (winkel, producten, kortingen, totaal),
       gevalideerd tegen een Pydantic-schema.
    3. De code controleert zelf of de som van alle lijnen gelijk is aan het totaal.
       Klopt dat niet, dan staat het ticket "ter controle" voor de gebruiker.
    4. Meldt het model onzekerheden, dan ook "ter controle": een onleesbaar bedrag dat
       uit het totaal werd afgeleid, maakt de som-controle anders circulair.

Bedragen staan altijd in integer centen (geen floats voor geld).
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, Field

# --- Instellingen (alles op één plek) ---------------------------------------
MODEL = "claude-opus-5-5"
EFFORT = "medium"           # low | medium | high: hoeveel het model nadenkt
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # API-limiet per afbeelding
MAX_LONG_SIDE_PX = 2400     # grote gsm-foto's worden hierheen verkleind
OUTPUT_DIR = Path(__file__).parent / "output"

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


# --- Het schema: wat we van het model terug willen --------------------------
class Regel(BaseModel):
    omschrijving: str = Field(description="Productnaam zoals op het ticket")
    aantal: float = Field(description="Aantal stuks, of gewicht in kg bij weegwaren")
    bedrag_cent: int = Field(description="Lijntotaal in centen, vóór kortingen. Leeggoed telt ook als regel")


class Korting(BaseModel):
    omschrijving: str = Field(description="Bv. '2+1 gratis', '-30%', 'Xtra-korting'")
    bedrag_cent: int = Field(description="Kortingsbedrag in centen, NEGATIEF (bv. -150)")
    hoort_bij: str | None = Field(description="Op welk product de korting slaat, als dat te zien is")


class Kasticket(BaseModel):
    winkel: str
    datum: str | None = Field(description="Formaat JJJJ-MM-DD, of null als onleesbaar")
    regels: list[Regel]
    kortingen: list[Korting]
    totaal_cent: int = Field(description="Het eindtotaal dat betaald werd, in centen")
    betaalwijze: str | None
    onzekerheden: list[str] = Field(
        description="Alles wat onleesbaar of twijfelachtig was. Leeg als alles duidelijk was"
    )


PROMPT = """Lees dit kasticket uit (meestal een Belgische of Nederlandse winkel).

Regels:
- Neem elk product op als aparte regel, met het lijntotaal VÓÓR korting.
- Neem elke korting, actie of promotie op als aparte korting met een NEGATIEF bedrag.
  Koppel ze aan het juiste product als het ticket dat toont.
- Leeggoed, statiegeld of zakjes zijn ook regels.
- Alle bedragen in centen (€ 2,49 wordt 249).
- totaal_cent is het bedrag dat effectief betaald werd.
- Verzin niets. Is iets onleesbaar, zet je beste lezing in de data en vermeld het bij onzekerheden.
"""


# --- Afbeelding voorbereiden -------------------------------------------------
def laad_afbeelding(pad: Path) -> tuple[str, str]:
    """Geeft (media_type, base64-data). Verkleint grote foto's tot onder de API-limiet."""
    suffix = pad.suffix.lower()
    if suffix in (".heic", ".heif"):
        sys.exit("HEIC-foto's (iPhone) worden niet ondersteund. Maak een screenshot of exporteer als JPG.")
    if suffix not in MEDIA_TYPES:
        sys.exit(f"Onbekend bestandstype '{suffix}'. Gebruik JPG, PNG, WEBP of GIF.")

    data = pad.read_bytes()
    media_type = MEDIA_TYPES[suffix]

    if len(data) > MAX_IMAGE_BYTES:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((MAX_LONG_SIDE_PX, MAX_LONG_SIDE_PX))
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)
        data = buffer.getvalue()
        media_type = "image/jpeg"
        print(f"(foto verkleind naar {len(data) // 1024} KB)")

    return media_type, base64.standard_b64encode(data).decode("utf-8")


# --- Claude aanroepen --------------------------------------------------------
def lees_ticket(client: anthropic.Anthropic, pad: Path) -> Kasticket:
    media_type, b64 = laad_afbeelding(pad)

    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        output_format=Kasticket,
        # Weigert het model om veiligheidsredenen, dan neemt automatisch een ander model over.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    )

    if response.stop_reason == "refusal":
        sys.exit("Het model weigerde dit ticket te verwerken.")
    if response.stop_reason == "max_tokens":
        sys.exit("Het antwoord werd afgekapt (max_tokens). Probeer een kleinere foto.")
    if response.parsed_output is None:
        sys.exit("Geen geldige data teruggekregen.")

    u = response.usage
    print(f"(tokens: {u.input_tokens} in / {u.output_tokens} uit)")
    return response.parsed_output


# --- De controle: hier zit de betrouwbaarheid --------------------------------
def controleer(ticket: Kasticket) -> int:
    """Geeft het verschil in centen tussen (regels + kortingen) en het totaal. 0 = klopt."""
    som = sum(r.bedrag_cent for r in ticket.regels) + sum(k.bedrag_cent for k in ticket.kortingen)
    return som - ticket.totaal_cent


def euro(cent: int) -> str:
    teken = "-" if cent < 0 else ""
    return f"{teken}€ {abs(cent) // 100},{abs(cent) % 100:02d}"


def toon(ticket: Kasticket, verschil: int) -> None:
    print()
    print(f"🧾 {ticket.winkel}  ·  {ticket.datum or 'datum onbekend'}  ·  {ticket.betaalwijze or ''}")
    print("─" * 60)
    for r in ticket.regels:
        aantal = f"{r.aantal:g}x" if r.aantal != 1 else "  "
        print(f"  {aantal:>6} {r.omschrijving[:38]:<38} {euro(r.bedrag_cent):>12}")
    if ticket.kortingen:
        print("  Kortingen:")
        for k in ticket.kortingen:
            bij = f" ({k.hoort_bij})" if k.hoort_bij else ""
            print(f"         {(k.omschrijving + bij)[:38]:<38} {euro(k.bedrag_cent):>12}")
    print("─" * 60)
    print(f"  {'TOTAAL op ticket':<45} {euro(ticket.totaal_cent):>12}")
    print()

    if verschil == 0 and ticket.onzekerheden:
        # De som klopt, maar het model meldt dat het iets niet kon lezen. Dan heeft het
        # mogelijk een bedrag afgeleid UIT het totaal, en is de som-controle circulair.
        print("⚠️  TER CONTROLE: de som klopt, maar het model kon niet alles lezen.")
        print("    Een afgeleid bedrag past altijd bij het totaal, dus een mens moet dit nakijken.")
    elif verschil == 0:
        print("✅ Controle OK: de som van alle lijnen is gelijk aan het totaal.")
    else:
        print(f"⚠️  TER CONTROLE: de lijnen tellen op tot {euro(ticket.totaal_cent + verschil)}, "
              f"het ticket zegt {euro(ticket.totaal_cent)} (verschil {euro(verschil)}).")
        print("    De gebruiker moet dit nakijken voor het wordt opgeslagen.")

    if ticket.onzekerheden:
        print("\n🔎 Onzekerheden die het model zelf meldde:")
        for o in ticket.onzekerheden:
            print(f"   - {o}")


def main() -> None:
    # Windows-terminals gebruiken soms cp1252, en dan crashen emoji's.
    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) != 2:
        sys.exit("Gebruik: python kasticket.py <pad-naar-foto>")
    pad = Path(sys.argv[1])
    if not pad.is_file():
        sys.exit(f"Bestand niet gevonden: {pad}")

    load_dotenv(Path(__file__).parent / ".env")
    client = anthropic.Anthropic()

    try:
        ticket = lees_ticket(client, pad)
    except anthropic.AuthenticationError:
        sys.exit("API-sleutel ongeldig. Kijk je .env-bestand na.")
    except anthropic.RateLimitError:
        sys.exit("Te veel aanvragen of tegoed op. Probeer later opnieuw of kijk je Billing na.")
    except anthropic.APIStatusError as e:
        sys.exit(f"API-fout {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("Geen verbinding met de API. Kijk je internet na.")

    verschil = controleer(ticket)
    toon(ticket, verschil)

    OUTPUT_DIR.mkdir(exist_ok=True)
    uit = OUTPUT_DIR / f"{pad.stem}.json"
    klopt = verschil == 0 and not ticket.onzekerheden
    resultaat = ticket.model_dump() | {"controle": {"klopt": klopt, "verschil_cent": verschil}}
    uit.write_text(json.dumps(resultaat, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n💾 Opgeslagen: {uit}")


if __name__ == "__main__":
    main()
