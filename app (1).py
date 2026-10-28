"""
IoT-Based CNC Machine Condition Monitoring - Streamlit Dashboard
Simulation-based proof of concept. Data comes from a Wokwi ESP32 simulation
over a public MQTT broker. Health score is rule-based (not machine learning).
"""
import json
import threading
import time
from collections import deque

import pandas as pd
import paho.mqtt.client as mqtt
import streamlit as st

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "cncmonitor_harshada2026/cnc/data"   # must match sketch.ino
STALE_AFTER_S = 10        # no message for this long -> "no live data"
HISTORY = 300             # readings kept in memory

# Same thresholds as the ESP32 sketch (for the alert text only;
# the score and condition always come from the ESP32).
TEMP_WARN, TEMP_CRIT = 35, 40
LOAD_WARN, LOAD_CRIT = 70, 85
VIB_WARN, VIB_CRIT = 60, 80

st.set_page_config(page_title="CNC Condition Monitor", layout="wide")


@st.cache_resource
def start_mqtt():
    """Create one MQTT client for the whole app and keep it running in a thread."""
    store = {
        "lock": threading.Lock(),
        "rows": deque(maxlen=HISTORY),
        "connected": False,
    }

    def on_connect(client, userdata, *args):
        store["connected"] = True
        client.subscribe(TOPIC)

    def on_disconnect(client, userdata, *args):
        store["connected"] = False

    def on_message(client, userdata, msg):
        try:
            d = json.loads(msg.payload.decode())
            d["time"] = pd.Timestamp.now()
            with store["lock"]:
                store["rows"].append(d)
        except Exception:
            pass  # ignore malformed messages

    try:  # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:  # paho-mqtt 1.x
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(BROKER, PORT, keepalive=30)
    client.loop_start()
    store["client"] = client
    return store


store = start_mqtt()


def alerts_for(r):
    out = []
    t, l, v = r["temperature"], r["load"], r["vibration"]
    if t > TEMP_CRIT:
        out.append(f"CRITICAL: temperature {t:.1f} C")
    elif t >= TEMP_WARN:
        out.append(f"WARNING: temperature {t:.1f} C")
    if l > LOAD_CRIT:
        out.append(f"CRITICAL: machine load {l:.0f} %")
    elif l >= LOAD_WARN:
        out.append(f"WARNING: machine load {l:.0f} %")
    if v > VIB_CRIT:
        out.append(f"CRITICAL: simulated vibration {v:.0f} %")
    elif v >= VIB_WARN:
        out.append(f"WARNING: simulated vibration {v:.0f} %")
    return out


st.title("IoT-Based CNC Machine Condition Monitoring")
st.caption(
    "Simulation-based proof of concept (Wokwi ESP32 + MQTT). "
    "Load and vibration are simulated with potentiometers; the health score is "
    "rule-based, not machine learning."
)


@st.fragment(run_every=2)
def live_view():
    with store["lock"]:
        rows = list(store["rows"])

    c1, c2 = st.columns(2)
    c1.write(f"**Broker:** {'connected' if store['connected'] else 'not connected'} "
             f"({BROKER}:{PORT})")
    c2.write(f"**Topic:** `{TOPIC}`")

    if not rows:
        st.info("Waiting for data. Start the Wokwi simulation and check the topic name.")
        return

    r = rows[-1]
    age = (pd.Timestamp.now() - r["time"]).total_seconds()
    if age > STALE_AFTER_S:
        st.warning(f"No new data for {age:.0f} s. Showing the last received reading "
                   "(is the Wokwi simulation running?).")

    cond = r["condition"]
    msg = f"Condition: {cond}  |  Health score: {r['health']}/100  |  Machine: {r['status']}"
    if cond == "HEALTHY":
        st.success(msg)
    elif cond in ("WARNING", "INSPECTION REQUIRED"):
        st.warning(msg)
    else:
        st.error(msg)

    m = st.columns(5)
    m[0].metric("Temperature (C)", f"{r['temperature']:.1f}")
    m[1].metric("Humidity (%)", f"{r['humidity']:.0f}")
    m[2].metric("Load (%)", f"{r['load']:.0f}")
    m[3].metric("Vibration (sim, %)", f"{r['vibration']:.0f}")
    m[4].metric("Health score", r["health"])
    st.progress(max(0, min(100, int(r["health"]))) / 100)

    st.subheader("Alerts")
    al = alerts_for(r)
    if al:
        for a in al:
            st.write("- " + a)
        if len(al) >= 2:
            st.write("- Multiple abnormal parameters")
    else:
        st.write("No active alerts.")

    df = pd.DataFrame(rows).set_index("time")
    st.subheader("Trends")
    t1, t2 = st.columns(2)
    t1.caption("Temperature (C)")
    t1.line_chart(df[["temperature"]])
    t2.caption("Health score")
    t2.line_chart(df[["health"]])
    t3, t4 = st.columns(2)
    t3.caption("Load and simulated vibration (%)")
    t3.line_chart(df[["load", "vibration"]])
    t4.caption("Humidity (%)")
    t4.line_chart(df[["humidity"]])

    st.subheader("Recent readings")
    st.dataframe(df.tail(15).iloc[::-1], use_container_width=True)
    st.download_button(
        "Download log (CSV)",
        df.reset_index().to_csv(index=False),
        file_name="cnc_log.csv",
        mime="text/csv",
        key=f"dl{int(time.time())}",
    )


live_view()
