"""Genereert realistische testtickets (Belgische supermarkt-stijl) in tickets/.

Bewust lastig gemaakt: acties ("2+1", "2e aan halve prijs"), kortingen in %,
weegwaren, leeggoed en een "u hebt bespaard"-regel die NIET dubbel geteld mag worden.
Elk ticket wordt licht gedraaid en vervaagd, zoals een echte gsm-foto.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "C:/Windows/Fonts/consola.ttf"
OUT = Path(__file__).parent / "tickets"
W = 42  # tekens per regel, zoals een echte kassaprinter

TICKETS = {
    "colruyt": [
        "C", "COLRUYT", "Laagste prijzen", "Colruyt Beringen", "13/10/2026 17:42   Kassa 04", "-",
        ("Coca-Cola Zero 1,5L", ""), ("   3 x 1,99", "5,97"),
        ("Bananen", ""), ("   0,834 kg x 1,99 EUR/kg", "1,66"),
        ("Jupiler 24x25cl", "17,49"),
        ("Leeggoed bak Jupiler", "3,90"),
        ("Boni Volle melk 1L", ""), ("   2 x 1,05", "2,10"),
        ("Lay's Paprika 250g", "3,29"),
        "-",
        ("Promo 2+1 gratis Coca-Cola", "-1,99"),
        ("Korting -30% Lay's Paprika", "-0,99"),
        "-",
        ("TOTAAL", "31,43"),
        ("Bancontact", "31,43"),
        "", "Aantal artikelen: 9", "Bedankt en tot ziens!",
    ],
    "lidl": [
        "C", "LIDL", "Lidl Heusden-Zolder", "12/10/2026 10:15", "-",
        ("Volkoren brood 800g", "1,49"),
        ("Kipfilet 600g", "6,99"),
        ("  Lidl Plus korting", "-1,40"),
        ("Tomaten", ""), ("  0,512 kg x 2,79 EUR/kg", "1,43"),
        ("Pindakaas 350g", ""), ("  2 x 2,30", "4,60"),
        ("  2e aan halve prijs", "-1,15"),
        ("Afwasmiddel 500ml", "2,19"),
        "-",
        ("Te betalen", "14,15"),
        ("Bancontact", "14,15"),
        "",
        "C", "*** Met Lidl Plus bespaard: 2,55 ***",
        "", "Bedankt voor uw bezoek",
    ],
}


def regels_naar_tekst(regels: list) -> list[str]:
    uit, centreer = [], False
    for r in regels:
        if r == "C":
            centreer = True
            continue
        if r == "-":
            uit.append("-" * W)
        elif isinstance(r, tuple):
            links, rechts = r
            uit.append(links.ljust(W - len(rechts)) + rechts)
        else:
            uit.append(r.center(W) if centreer else r)
            if r == "":
                centreer = False
    return uit


def teken(naam: str, regels: list, hoek: float, vlek_op_regel: int | None = None) -> None:
    font = ImageFont.truetype(FONT, 26)
    tekst = regels_naar_tekst(regels)
    lijn_h, marge = 34, 40
    breedte = int(font.getlength("M") * W) + 2 * marge
    hoogte = lijn_h * len(tekst) + 2 * marge

    papier = Image.new("RGB", (breedte, hoogte), (250, 248, 240))
    d = ImageDraw.Draw(papier)
    for i, lijn in enumerate(tekst):
        d.text((marge, marge + i * lijn_h), lijn, font=font, fill=(40, 40, 45))

    if vlek_op_regel is not None:
        # Koffievlek over de prijs rechts op die regel: test voor de controle
        y = marge + vlek_op_regel * lijn_h + lijn_h // 2
        x = breedte - marge - 50
        d.ellipse((x - 55, y - 30, x + 45, y + 28), fill=(150, 115, 80))

    # "Foto": ticket op een tafel, licht gedraaid en een beetje wazig
    achtergrond = Image.new("RGB", (breedte + 160, hoogte + 160), (120, 110, 100))
    achtergrond.paste(papier, (80, 80))
    foto = achtergrond.rotate(hoek, resample=Image.BICUBIC, fillcolor=(120, 110, 100))
    foto = foto.filter(ImageFilter.GaussianBlur(0.7))
    foto.save(OUT / f"{naam}.jpg", quality=85)
    print(f"gemaakt: tickets/{naam}.jpg")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    teken("colruyt", TICKETS["colruyt"], hoek=1.8)
    teken("lidl", TICKETS["lidl"], hoek=-2.5)
    # Zelfde Colruyt-ticket, maar met een vlek over de prijs van de Jupiler (regel 9)
    teken("colruyt_vlek", TICKETS["colruyt"], hoek=1.2, vlek_op_regel=9)
