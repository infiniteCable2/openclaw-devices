"""Read this node's sticker credentials over its USB-UART console; never flash it."""
import argparse
import hashlib
import json
import queue
import re
import sys
import threading
import time

REQUEST = b"netnode setup-access v1\n"


def parse_access(line):
    """Ignore boot logs and accept only the versioned, bounded firmware reply."""
    if len(line) > 512:
        return None
    try:
        data = json.loads(line)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("type") != "netnode.setup-access":
        return None
    if type(data.get("version")) is not int or data["version"] != 1:
        return None
    if not isinstance(data.get("ssid"), str) or not re.fullmatch(r"OpenClaw-Setup-[0-9A-F]{6}", data["ssid"]):
        return None
    if not isinstance(data.get("password"), str) or not re.fullmatch(r"[0-9a-f]{24}", data["password"]):
        return None
    if data.get("username") != "admin" or data.get("url") != "http://192.168.4.1":
        return None
    checksum = hashlib.sha256(f"{data['ssid']}\n{data['password']}".encode("ascii")).hexdigest()
    if data.get("sha256") != checksum:
        return None
    return {key: data[key] for key in ("ssid", "password", "username", "url")}


def query_access(port, timeout=12.0):
    import serial

    # Set line states before opening: no deliberate EN/BOOT reset sequence.
    connection = serial.Serial(port=None, baudrate=115200, timeout=0.2, write_timeout=1)
    connection.dtr = False
    connection.rts = False
    connection.port = port
    pending = bytearray()
    dropping = False
    try:
        connection.open()
        deadline = time.monotonic() + timeout
        next_request = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_request:
                connection.write(REQUEST)
                next_request = now + 1.2
            for value in connection.read(256):
                if value == 10:
                    if not dropping:
                        result = parse_access(bytes(pending))
                        if result is not None:
                            return result
                    pending.clear()
                    dropping = False
                elif not dropping:
                    pending.append(value)
                    if len(pending) > 512:
                        pending.clear()
                        dropping = True
        raise TimeoutError("Keine passende Antwort. Neue Firmware installiert? Richtiger Port? Seriellen Monitor schließen.")
    finally:
        connection.close()


def access_text(data):
    return (
        f"WLAN: {data['ssid']}\nHotspot-Passwort: {data['password']}\n"
        f"Einrichtung: {data['url']}\nBenutzer: {data['username']}\n\n"
        "Das Sticker-Passwort bleibt bei einem Werksreset erhalten.\n"
        "Es ist auch das Web-Passwort nach Ersteinrichtung / Werksreset.\n"
        "Ein später geändertes Web-Passwort wird nicht ausgelesen."
    )


def available_ports():
    from serial.tools import list_ports
    return sorted(list_ports.comports(), key=lambda entry: entry.device)


def launch_gui():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("OpenClaw Node – Sticker-Zugangsdaten")
    root.geometry("660x360")
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="ESP per USB anschließen und den seriellen Monitor schließen.").pack(anchor="w")
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=12)
    port = ttk.Combobox(row, state="readonly", width=45)
    port.pack(side="left", fill="x", expand=True)
    choices = {}
    messages = queue.Queue()
    output = tk.Text(frame, height=11, wrap="word", state="disabled")

    def show(message):
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", message)
        output.configure(state="disabled")

    def refresh():
        try:
            entries = available_ports()
            choices.clear()
            choices.update({f"{item.device} – {item.description}": item.device for item in entries})
            port["values"] = list(choices)
            port.set(next(iter(choices), ""))
            show("Port auswählen und auf Auslesen klicken." if choices else "Kein serieller Port gefunden.")
        except Exception:
            show("USB-Zugriff fehlt. Bitte zuerst: py -3 -m pip install -r tools/requirements.txt")

    refresh_button = ttk.Button(row, text="Aktualisieren", command=refresh)
    refresh_button.pack(side="left", padx=(8, 0))

    def read():
        selected = choices.get(port.get())
        if not selected:
            show("Bitte einen Port auswählen.")
            return
        read_button.configure(state="disabled")
        refresh_button.configure(state="disabled")
        port.configure(state="disabled")
        show("Lese Zugangsdaten …")

        def worker():
            try:
                messages.put(access_text(query_access(selected)))
            except TimeoutError as error:
                messages.put(str(error))
            except Exception:
                messages.put("Port konnte nicht gelesen werden. Kabel/Port prüfen und seriellen Monitor schließen.")

        threading.Thread(target=worker, daemon=True).start()

    read_button = ttk.Button(frame, text="Zugangsdaten auslesen", command=read)
    read_button.pack(anchor="w", pady=(0, 10))
    output.pack(fill="both", expand=True)

    def poll():
        try:
            show(messages.get_nowait())
            read_button.configure(state="normal")
            refresh_button.configure(state="normal")
            port.configure(state="readonly")
        except queue.Empty:
            pass
        root.after(100, poll)

    refresh()
    poll()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="USB-UART-Port, z. B. COM3 oder /dev/ttyUSB0 (Textausgabe)")
    parser.add_argument("--list", action="store_true", help="Verfügbare Ports anzeigen")
    parser.add_argument("--gui", action="store_true", help="Fenster öffnen (Standard ohne --port)")
    args = parser.parse_args()
    try:
        if args.list:
            for entry in available_ports():
                print(f"{entry.device}: {entry.description}")
        elif args.port and not args.gui:
            print(access_text(query_access(args.port)))
        else:
            launch_gui()
    except ImportError:
        print("Bitte Python mit Tkinter und pyserial installieren: python -m pip install -r tools/requirements.txt", file=sys.stderr)
        return 1
    except TimeoutError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("USB-Zugriff fehlgeschlagen. Port, Kabel und andere serielle Programme prüfen.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
