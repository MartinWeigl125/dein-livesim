import os
import random
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from supabase import create_client, Client

# Supabase-Zugangsdaten
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL und SUPABASE_KEY müssen als Umgebungsvariablen gesetzt sein!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Zeitzone
tz_berlin = ZoneInfo("Europe/Berlin")

# Simulationseinstellungen
device_id = 2
interval = 120  # Sekunden

# Startwerte
actual_temp = 21.0
set_temp = 22.0
valve_pos = 50

boost_remaining = 0
battery_low_remaining = 0

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

print("Starte Live-Simulation...")

while True:
    current_time = datetime.now(tz_berlin)

    # SET Temp
    # aus der Datenbank die aktuelle eingestellte Temperatur und den aktuellen Modus holen
    response = supabase.table("devices").select("current_set_temp, current_mode").eq("device_id", device_id).execute()

    # Wert extrahieren
    if response.data and len(response.data) > 0:
        set_temp = response.data[0]["current_set_temp"]
        current_mode = response.data[0]["current_mode"]
    else:
        set_temp = 22.0
        current_mode = "MANU"
        print("[!] Fehler beim Lesen der eingestellten Temperatur und Modus, default Wert wird verwendet.")

    # aus der Datenbank den nächsten Zeitpunkt für den PARTY Modus holen
    response = supabase.rpc("get_current_or_next_party", {
        "input_device_id": device_id,
        "input_now": current_time.isoformat()
    }).execute()

    next_party = response.data if response.data else None

    if next_party and "from_ts" in next_party and "to_ts" in next_party:
        from_ts = datetime.fromisoformat(next_party["from_ts"])
        to_ts = datetime.fromisoformat(next_party["to_ts"])
        if from_ts <= current_time <= to_ts:
            current_mode = "PARTY"

    if current_mode == "AUTO":
        today = WEEKDAYS[current_time.weekday()]
        current_strftime = current_time.time().strftime("%H:%M:%S")

        # Hole alle Weekplan-Einträge für das Gerät
        response = (
            supabase.table("device_weekplans")
            .select("weekday, time, temperature")
            .eq("device_id", device_id)
            .order("weekday")
            .order("time")
            .execute()
        )

        if not response.data:
            set_temp = 21 # default value

        # Sortiere alle Einträge in sinnvoller Wochenreihenfolge
        def weekday_index(entry):
            return WEEKDAYS.index(entry["weekday"])

        all_entries = sorted(response.data, key=lambda r: (weekday_index(r), r["time"]))

        # Finde den letzten Eintrag <= jetzt (in Woche rotierend rückwärts)
        now_index = WEEKDAYS.index(today)
        candidates = []

        for entry in all_entries:
            entry_index = WEEKDAYS.index(entry["weekday"])
            if entry_index < now_index or (entry_index == now_index and entry["time"] <= current_strftime):
                candidates.append((entry_index, entry["time"], entry["temperature"]))

        if candidates:
            # Letzter gültiger Eintrag vor jetzigem Zeitpunkt
            set_temp = candidates[-1][2]
        else:
            # Kein gültiger Eintrag diese Woche bis jetzt – nimm den letzten in der Liste
            set_temp = all_entries[-1]["temperature"]

    # BATTERY
    if battery_low_remaining > 0:
        battery_low = True
        battery_low_remaining -= 1
    else:
        if random.random() < 0.005:
            battery_low_remaining = random.randint(30, 200)
            battery_low = True
        else:
            battery_low = False

    # Temperaturentwicklung
    temp_diff = set_temp - actual_temp
    environment_effect = random.uniform(-0.05, 0.05)
    heating_effect = valve_pos / 100.0 * 0.2
    actual_temp += 0.1 * temp_diff + heating_effect + environment_effect
    actual_temp = round(actual_temp, 1)

    # Ventilposition
    target_valve = round(min(max(50 + temp_diff * 15 + random.uniform(-3, 3), 0), 100))
    if current_mode == "BOOST":
        valve_pos = 100
    else:
        valve_pos += int((target_valve - valve_pos) * 0.2)
        valve_pos = min(max(valve_pos, 0), 100)

    # Datenpaket
    data = {
        "device_id": device_id,
        "timestamp": current_time.isoformat(),
        "actual_temperature": round(actual_temp, 1),
        "set_temperature": round(set_temp, 1),
        "valve_position": valve_pos,
        "boost_state": current_mode == "BOOST",
        "battery_low": battery_low,
        "control_mode": current_mode
    }

    # In Supabase einfügen
    try:
        response = supabase.table("thermostat_readings").insert(data).execute()
        print(f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] Datensatz geschrieben.")
    except Exception as e:
        print(f"Fehler beim Schreiben in Supabase: {e}")

    time.sleep(interval)
