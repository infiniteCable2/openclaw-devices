# ESP32 Mini Case – 30 Pin / USB-C, Deckel v0.3

Kleines zweiteiliges Gehäuse für die fotografierte ESP-WROOM-32-Platine mit
angelöteten Stiftleisten, 15 Pins je Seite und USB-C. **Case und Lid sind separate
STLs.** Der Deckel läuft in seitlichen Führungen und wird durch eine elastische
Rastlasche gegen Herausschieben gehalten. Es werden keine Schrauben benötigt.

**Das bereits gedruckte Case passt laut Rückmeldung. `case.stl` ist unverändert;
für diese Revision muss nur `lid.stl` neu gedruckt werden.** Die Deckfläche sitzt
jetzt 1,2 mm höher und deckt den oberen Case-Rand ab. Sie folgt der gerundeten
Außenkontur mit 0,2 mm Einzug pro Seite. Der Clip bleibt auf seiner bisherigen
Höhe in einer nach hinten offenen Griffmulde. Die sieben geraden, abgerundeten
Lüftungsschlitze der ersten Version sind zurück. Der geschlossene USB-Abschluss
und die leicht angefasten Tasteröffnungen bleiben erhalten.

## Dateien

| Datei | Zweck | Außenmaß in mm |
| --- | --- | --- |
| `case.stl` | Unterteil mit Pinführungen und USB-Öffnung | 58 × 34 × 19 |
| `lid.stl` | Erhöhter Schiebedeckel mit vertieftem Clip | 57,6 × 33,6 × 4,2 |
| `pin-fit-test.stl` | Kleine Passprobe für beide Pinreihen | 9 × 34 × 9 |
| `preview.html` | Offline drehbare Ansicht der tatsächlichen CAD-Netze | – |
| `preview.png` | Vorschau des Entwurfs | – |
| `dimensions.json` | Veränderbare Hauptmaße in mm | – |
| `generate.py` | Parametrischer CAD-Generator | – |
| `verification.json` | Netzprüfung, Freiräume und STL-Prüfsummen | – |

Geschlossen beträgt das Außenmaß **58 × 34 × 20,2 mm**. Das Case selbst bleibt
19 mm hoch. Die frühere überstehende Querleiste entfällt weiterhin.
Die Platine in der Vorschau ist eine vereinfachte Maßreferenz
und kein zusätzliches Druckteil.

## Maße und erste Passprobe

Die Ausgangsmaße wurden aus Fotos geschätzt. Die Passung des Unterteils wurde
anschließend am gedruckten Teil bestätigt; der Deckel v0.3 ist noch nicht
druckerprobt. Verwendet werden:

- PCB 52 × 28,5 × 1,6 mm.
- Zwei Reihen mit jeweils 15 Pins, Raster 2,54 mm und Reihenmittenabstand 25,4 mm.
- Erste Pinmitte etwa 9,6 mm von der USB-seitigen Platinenkante.
- Kunststoffleiste 2,5 mm hoch; freie Pins höchstens etwa 6,2 mm lang.
- Bauteile höchstens 3,2 mm über der Platinenoberseite.

2,54 mm Raster ist für solche Boards üblich; der Abstand zwischen den Reihen ist
bei ESP32-Varianten unterschiedlich. Zum Vergleich nennt
[Joy-IT](https://joy-it.net/en/products/SBC-ESP-BO1) 22,86 und 25,4 mm.
Die ähnliche [30-Pin-USB-C-Platine bei Nettigo](https://nettigo.eu/products/esp-32-wifi-bluetooth-development-module-30-pin-version-usb-c)
wird mit 52 × 28,5 mm beschrieben. Damit ist der konkrete Hersteller der
fotografierten Platine noch nicht eindeutig bestimmt.

**Bei weiteren, noch nicht geprüften Boards zuerst `pin-fit-test.stl` drucken.**
Für das bereits passende Board ist das nicht erneut nötig.
Die jeweils letzten drei Pins beider Reihen
vorsichtig in die Probe stecken; die übrigen Pins liegen außerhalb der Probe.
Die Kunststoffleisten sollen auf den Schienen aufliegen. Kein kraftvolles
Einpressen: Die Löcher sind als lockere Führung ausgelegt. Stimmen Reihenabstand
oder Raster nicht, vor dem Gehäusedruck messen und `dimensions.json` anpassen.
Die Probe prüft Pinführung und Einstecktiefe; PCB-Länge, USB-Position und
Deckelpassung müssen anschließend am vollständigen Prototyp geprüft werden.

## Druck und Montage

- STL im Slicer als **Millimeter**, Skalierung **100 %** importieren.
- PETG empfohlen: 0,4-mm-Düse, 0,2-mm-Schichten, drei Wände und etwa 15–25 % Infill.
  PLA ist für einen ersten Passversuch möglich; die Rastlasche vorsichtig bedienen.
- Beide STLs liegen bereits auf der vorgesehenen Druckseite: Case mit Boden
  unten, Lid mit der erhöhten flachen Außenseite unten. Die Rastnase zeigt
  beim Deckeldruck nach oben.
- **Deckel v0.3 benötigt lokale Stützen in der vertieften Clipmulde.**
  Die Clipfläche beginnt bei dieser Druckausrichtung erst 1,2 mm über dem
  Druckbett. Druckbett-Stützen auf diese Mulde einschließlich ihres schmalen
  hinteren Stegs begrenzen; nach dem Druck vorsichtig entfernen. Ein
  Stützabstand von etwa einer Schicht ist ein Ausgangswert für den Slicer.
  Die seitlichen Führungen haben weiterhin 45°-Flächen. In der Schichtvorschau
  die offenen Passlöcher, Schienen und Freischnitte der Lasche prüfen.
- Board mit den Pins nach unten einsetzen. USB zeigt zur großen Aussparung;
  Antenne und Deckelöffnung liegen an der gegenüberliegenden Seite.
- Deckel von der Antennenseite in die vorhandenen seitlichen Schienen
  einschieben. Die Rastnase greift weiterhin hinter die innere Rückwand.
  Die vorderen Deckelschultern begrenzen den Einschub an der vorhandenen
  inneren Frontwand; ein äußerer hinterer Endanschlag ist nicht mehr nötig.
  Die erhöhte Deckfläche deckt den Case-Rand ab. Zwischen ihrer Unterseite und
  dem vorhandenen Rand liegen 0,2 mm vertikale Gleitluft; außen bleibt sie
  nominell 0,2 mm innerhalb der Case-Kontur.
  Die etwa 0,2 mm vordere und
  0,15 mm hintere Bewegungsfreiheit bleiben innerhalb der Case-Außenkontur.
- Zum Öffnen die hintere Lasche am ovalen Griffloch etwa 0,6–0,8 mm anheben und
  den Deckel zur Antennenseite herausziehen. Bei klemmender Passung nicht hebeln,
  sondern Führungen entgraten bzw. die Druckpassung anpassen.

Die 30 Sacklöcher sind 1,7 mm weit, mit etwa 2,1 mm Einlauf. Die Pinspitzen haben
rechnerisch 0,8 mm Platz zum Lochboden. Die Kunststoffleisten tragen das Board;
die Pins werden nicht als Presspassung belastet. Anschläge an den Platinenkanten
begrenzen die Bewegung beim Einstecken des USB-Kabels. Der geschlossene Deckel
begrenzt das Anheben der Platine. USB, beide Taster und Belüftung bleiben
zugänglich. Die Unterseite des USB-Stegs bleibt bei 17,8 mm über dem Case-Boden
und lässt zur vereinfachten USB-Buchsenreferenz rechnerisch 1,5 mm Luft. Mit der
erhöhten Deckfläche ist dieser Steg jetzt 2,4 mm dick. Beim ersten
Passversuch des neuen Deckels auch das vollständige Einstecken des verwendeten
USB-Kabels prüfen. Der Innenraum über der Antenne enthält keine Befestigungsteile.

## Anpassen und neu erzeugen

Benötigt Python mit den Paketen aus `requirements.txt`, beispielsweise in einer
temporären virtuellen Umgebung:

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python generate.py
```

Unter Linux/macOS stattdessen `.venv/bin/python` verwenden. Die Umgebung nach
Gebrauch entfernen. `generate.py` erzeugt die drei STLs, `verification.json` und
die selbstständige `preview.html`; die HTML-Datei benötigt keinen Server und
keine externen Bibliotheken. `preview.png` ist eine separat gerenderte Aufnahme.

Die Maße in `dimensions.json` steuern den vorhandenen 30-Pin-Entwurf. USB-,
Taster- und Bauteilkonturen sowie die Rastgeometrie liegen zusätzlich im
Generator; ein anderes Boardformat erfordert deren Anpassung. `lid_raise`
bestimmt die Erhöhung und `lid_rim_clearance` die vertikale Gleitluft über dem
Case-Rand. Die elastische Clipfläche und die ursprüngliche Schiebeführung
bleiben bei dieser Erhöhung auf ihren bisherigen Z-Positionen. Die Geometrie wird
auf geschlossene zusammenhängende Netze, positive Volumen, nominelle
Bauteilfreiräume und 65 Positionen des Deckelschiebewegs geprüft. Zusätzlich
werden beide Anschlagrichtungen und die Außenkontur an den Spielgrenzen geprüft.
Der Unterteil-Export hat weiterhin SHA-256
`e96205394fe6171e27f1053b33a3eba5530040ab6c6e0edaefb575a86f0c04ed`, identisch mit
dem erfolgreich gedruckten Stand. Die elastische
Rastbewegung und reale Drucktoleranzen sind damit nicht physisch nachgewiesen.

**Status:** Case-Passung bestätigt und Case-Datei unverändert. Deckel v0.3 im CAD
geprüft; Passversuch am neuen Druck einschließlich USB-Kabel noch offen.
