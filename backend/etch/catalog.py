"""Parts catalog. Every part the agent may use, with pinout, footprint, LCSC number and design hints."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import footprints as F

# pin types: power_in | power_out | gnd | input | output | bidirectional | passive | nc
PWR, POUT, GND, IN, OUT, BI, PAS, NC = "power_in", "power_out", "gnd", "input", "output", "bidirectional", "passive", "nc"


@dataclass
class Part:
    id: str
    name: str
    category: str
    description: str
    footprint: F.Footprint
    pins: list[tuple[str, str, str]]  # (num, name, type)
    lcsc: str = ""
    price: float = 0.1
    power_w: float = 0.0
    value: str = ""
    hints: str = ""
    ref_prefix: str = "U"
    body_style: str | None = None

    def pin_by(self, key: str):
        key_l = key.lower()
        for num, name, typ in self.pins:
            if num.lower() == key_l or name.lower() == key_l:
                return (num, name, typ)
        # allow "IO21" to match "IO21/SDA"
        for num, name, typ in self.pins:
            if key_l in [s.lower() for s in name.replace("(", "/").replace(")", "").split("/")]:
                return (num, name, typ)
        return None

    def to_json(self):
        fp = self.footprint
        return {
            "part_id": self.id, "name": self.name, "category": self.category, "description": self.description,
            "footprint": fp.name, "package": fp.name.replace("_", " "),
            "lcsc": self.lcsc, "price_usd": self.price, "power_w": self.power_w,
            "pins": [{"num": n, "name": nm, "type": t} for n, nm, t in self.pins],
            "body": {"w": fp.body_w, "h": fp.body_h, "z": fp.body_z, "style": self.body_style or fp.style},
        }


CATALOG: dict[str, Part] = {}


def add(p: Part):
    CATALOG[p.id] = p
    return p


def P(*pins):
    """P(("1","GND",GND), ...) helper; also accepts strings "1:GND:gnd"."""
    out = []
    for p in pins:
        if isinstance(p, str):
            n, nm, t = p.split(":")
            out.append((n, nm, t))
        else:
            out.append(p)
    return out


def seq(names: list[str], types: list[str] | str):
    if isinstance(types, str):
        types = [types] * len(names)
    return [(str(i + 1), n, t) for i, (n, t) in enumerate(zip(names, types))]


def _t(name: str) -> str:
    n = name.upper()
    if n in ("GND", "VSS", "PGND", "AGND", "DGND", "VSSA", "EP", "GND/ADJ"):
        return GND
    if n.startswith(("VCC", "VDD", "VIN", "3V3", "5V", "VBUS", "VBAT", "AVCC", "AVDD", "DVDD", "VM", "PVDD", "VS", "VSUP", "V+", "VCCA", "VCCB", "VDDIO", "VLOGIC")):
        return PWR
    if n in ("VOUT", "OUT", "V3", "REGOUT", "VREF", "VINT", "VBG"):
        return POUT
    if n == "NC":
        return NC
    return BI


def auto(names: list[str]):
    return [(str(i + 1), n, _t(n)) for i, n in enumerate(names)]


# ============================================================ PASSIVES
for size in ("0402", "0603", "0805", "1206"):
    add(Part(f"r-{size}", f"Resistor {size}", "passive", f"Chip resistor, {size} imperial", F.chip(size),
             P(("1", "1", PAS), ("2", "2", PAS)), lcsc={"0402": "C25744", "0603": "C25804", "0805": "C17414", "1206": "C17902"}[size],
             price=0.005, value="10k", ref_prefix="R", hints="value like 10k, 4.7k, 330"))
    add(Part(f"c-{size}", f"Capacitor {size}", "passive", f"MLCC ceramic capacitor, {size} imperial", F.chip(size),
             P(("1", "1", PAS), ("2", "2", PAS)), lcsc={"0402": "C1525", "0603": "C14663", "0805": "C15850", "1206": "C13585"}[size],
             price=0.01, value="100nF", ref_prefix="C", hints="0603 up to 4.7uF; 0805 up to 22uF; 1206 up to 47uF"))
add(Part("c-elec-6.3", "Electrolytic cap 6.3mm SMD", "passive", "Aluminium electrolytic, 6.3x5.4mm SMD, 100–470uF", F.electrolytic_smd(),
         P(("1", "+", PAS), ("2", "-", PAS)), lcsc="C3343", price=0.06, value="220uF", ref_prefix="C", hints="pin 1 is +"))
add(Part("l-4x4", "Power inductor 4x4mm", "passive", "Shielded SMD power inductor 4x4x2mm, 2.2–22uH", F.inductor_4x4(),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C1760", price=0.08, value="10uH", ref_prefix="L"))
add(Part("fb-0603", "Ferrite bead 0603", "passive", "Ferrite bead 600R@100MHz", F.chip("0603"),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C1017", price=0.02, value="600R", ref_prefix="FB"))
add(Part("fuse-1206", "Fuse 1206", "protection", "SMD fuse 1206, e.g. 1A/2A", F.chip("1206"),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C182974", price=0.1, value="2A", ref_prefix="F"))
add(Part("led-0603", "LED 0603", "led", "Chip LED 0603; needs series resistor (~1k at 3.3V)", F.chip("0603", style="led"),
         P(("1", "K", PAS), ("2", "A", PAS)), lcsc="C2286", price=0.01, value="green", ref_prefix="D", power_w=0.01,
         hints="pin 1 cathode (K), pin 2 anode (A); value = colour"))
add(Part("led-0805", "LED 0805", "led", "Chip LED 0805", F.chip("0805", style="led"),
         P(("1", "K", PAS), ("2", "A", PAS)), lcsc="C84256", price=0.015, value="red", ref_prefix="D", power_w=0.02))
add(Part("ws2812b", "WS2812B RGB LED", "led", "Addressable RGB LED 5050, 5V, single-wire", F.led_5050(),
         P(("1", "VDD", PWR), ("2", "DOUT", OUT), ("3", "GND", GND), ("4", "DIN", IN)), lcsc="C2761795", price=0.05, value="RGB",
         ref_prefix="D", power_w=0.15, hints="chain DOUT→DIN; 100nF decoupling per LED; needs 5V"))
add(Part("d-sod123", "Diode SOD-123", "protection", "Signal/Schottky diode SOD-123 (1N4148W / B5819W)", F.sod123(),
         P(("1", "K", PAS), ("2", "A", PAS)), lcsc="C8598", price=0.02, value="B5819W", ref_prefix="D"))
add(Part("d-sma", "Schottky diode SMA", "protection", "Power Schottky SS34 3A/40V, SMA (DO-214AC)", F.sma_diode(),
         P(("1", "K", PAS), ("2", "A", PAS)), lcsc="C8678", price=0.04, value="SS34", ref_prefix="D",
         hints="use for reverse polarity protection or flyback"))
add(Part("tvs-usblc6", "USBLC6-2SC6 TVS", "protection", "USB ESD protection array, SOT-23-6", F.sot23(6),
         P(("1", "IO1", BI), ("2", "GND", GND), ("3", "IO2", BI), ("4", "IO2", BI), ("5", "VBUS", PWR), ("6", "IO1", BI)),
         lcsc="C7519", price=0.08, ref_prefix="U", hints="IO1/IO2 across D+/D-; VBUS to 5V"))
add(Part("tvs-smbj", "SMBJ TVS diode", "protection", "Uni-directional TVS 5V–24V, SMB", F.sma_diode(),
         P(("1", "K", PAS), ("2", "A", PAS)), lcsc="C121716", price=0.07, value="SMBJ5.0A", ref_prefix="D"))

# ============================================================ MCUs / modules
add(Part("esp32-wroom-32e", "ESP32-WROOM-32E", "mcu", "Wi-Fi + BLE dual-core module, 4MB flash, 38 pins", F.esp32_wroom(),
         auto(["GND", "3V3", "EN", "IO36/SENSOR_VP", "IO39/SENSOR_VN", "IO34", "IO35", "IO32", "IO33", "IO25", "IO26", "IO27", "IO14", "IO12",
               "GND", "IO13", "IO9/SD2", "IO10/SD3", "IO11/CMD", "IO6/CLK", "IO7/SD0", "IO8/SD1", "IO15", "IO2", "IO0", "IO4", "IO16", "IO17",
               "IO5", "IO18", "IO19", "NC", "IO21", "IO3/RXD0", "IO1/TXD0", "IO22", "IO23", "GND", "GND"]),
         lcsc="C701341", price=2.9, power_w=0.6,
         hints="3.3V only. EN: 10k pull-up to 3V3 + 100nF to GND. IO0 button to GND for boot. Decouple 3V3 with 10uF + 100nF. "
               "Pins 17–22 (SD0–SD3/CMD/CLK) are internal flash — never use. IO34–39 input-only. IO21=SDA, IO22=SCL by convention. "
               "UART0 (IO1/IO3) for programming via CH340C. IO12 must not be pulled high at boot. Keep antenna (top edge) at board edge."))
add(Part("esp32-s3-wroom-1", "ESP32-S3-WROOM-1", "mcu", "Wi-Fi + BLE5, native USB, 8MB flash, 40 pins", F.esp32_wroom("ESP32-S3-WROOM-1", 14, 12),
         auto(["GND", "3V3", "EN", "IO4", "IO5", "IO6", "IO7", "IO15", "IO16", "IO17", "IO18", "IO8", "IO19/USB_D-", "IO20/USB_D+",
               "IO3", "IO46", "IO9", "IO10", "IO11", "IO12", "IO13", "IO14", "IO21", "IO47", "IO48", "IO45", "IO0", "IO35", "IO36",
               "IO37", "IO38", "IO39", "IO40", "IO41", "IO42", "IO44/RXD0", "IO43/TXD0", "IO2", "IO1", "GND", "GND"]),
         lcsc="C2913202", price=3.4, power_w=0.6,
         hints="3.3V. Native USB on IO19 (D-) / IO20 (D+): connect USB-C D+/D- directly with 22R series optional, no CH340 needed. "
               "EN 10k pull-up + 100nF; IO0 boot button. IO35-37 unusable on octal-PSRAM variants; avoid."))
add(Part("esp32-c3-wroom-02", "ESP32-C3-WROOM-02", "mcu", "RISC-V Wi-Fi + BLE5 module, native USB-serial, 18 pins", F.esp32_c3_wroom02(),
         auto(["3V3", "EN", "IO4", "IO5", "IO6", "IO7", "IO8", "IO9", "GND", "IO10", "IO20/RXD", "IO21/TXD", "IO18/USB_D-", "IO19/USB_D+",
               "IO3", "IO2", "IO1", "IO0", "GND"]),
         lcsc="C2934569", price=2.1, power_w=0.4,
         hints="3.3V. IO18/IO19 = native USB-serial-JTAG: wire USB-C D-/D+ directly. IO9 boot button (pull-up 10k). IO8 must be high at boot. EN 10k pull-up + 100nF."))
add(Part("atmega328p-au", "ATmega328P-AU", "mcu", "8-bit AVR, TQFP-32, Arduino-compatible", F.lqfp(32, 0.8, 7.0),
         auto(["PD3", "PD4", "GND", "VCC", "GND", "VCC", "PB6/XTAL1", "PB7/XTAL2", "PD5", "PD6", "PD7", "PB0", "PB1", "PB2", "PB3/MOSI", "PB4/MISO",
               "PB5/SCK", "AVCC", "ADC6", "AREF", "GND", "ADC7", "PC0/A0", "PC1/A1", "PC2/A2", "PC3/A3", "PC4/SDA", "PC5/SCL", "PC6/RESET", "PD0/RXD", "PD1/TXD", "PD2"]),
         lcsc="C14877", price=1.6, power_w=0.05,
         hints="5V or 3.3V. 16MHz crystal on XTAL1/XTAL2 with 2x22pF (or run 8MHz internal). RESET 10k pull-up. 100nF on each VCC/AVCC. ICSP header: MISO/MOSI/SCK/RESET/VCC/GND."))
add(Part("attiny85", "ATtiny85-20SU", "mcu", "8-pin AVR, SOIC-8", F.soic(8),
         auto(["PB5/RESET", "PB3", "PB4", "GND", "PB0/MOSI", "PB1/MISO", "PB2/SCK", "VCC"]),
         lcsc="C89852", price=1.2, power_w=0.03, hints="100nF decoupling; RESET 10k pull-up; 5 usable GPIO"))
add(Part("stm32f103c8t6", "STM32F103C8T6", "mcu", "ARM Cortex-M3 72MHz, LQFP-48", F.lqfp(48, 0.5, 7.0),
         auto(["VBAT", "PC13", "PC14", "PC15", "PD0/OSC_IN", "PD1/OSC_OUT", "NRST", "VSSA", "VDDA", "PA0", "PA1", "PA2/TX2", "PA3/RX2", "PA4", "PA5/SCK1",
               "PA6/MISO1", "PA7/MOSI1", "PB0", "PB1", "PB2/BOOT1", "PB10/SCL2", "PB11/SDA2", "VSS", "VDD", "PB12", "PB13", "PB14", "PB15", "PA8", "PA9/TX1",
               "PA10/RX1", "PA11/USB_DM", "PA12/USB_DP", "PA13/SWDIO", "PA14/SWCLK", "PA15", "PB3", "PB4", "PB5", "PB6/SCL1", "PB7/SDA1", "BOOT0", "PB8", "PB9",
               "VSS", "VDD", "VSS", "VDD"]),
         lcsc="C8734", price=1.9, power_w=0.12,
         hints="3.3V. 8MHz crystal (HC-49 or 3225) on OSC_IN/OSC_OUT + 2x20pF. 100nF on every VDD, 10uF bulk. NRST 100nF. BOOT0 10k to GND. "
               "SWD header: SWDIO/SWCLK/GND/3V3. USB: PA11/PA12 with 1.5k pull-up on PA12 optional."))
add(Part("ch340c", "CH340C USB-UART", "ic", "USB to UART bridge, no crystal needed, SOP-16", F.soic(16),
         auto(["GND", "TXD", "RXD", "V3", "UD+", "UD-", "NC", "NC", "CTS", "DSR", "RI", "DCD", "DTR", "RTS", "R232", "VCC"]),
         lcsc="C84681", price=0.4, power_w=0.03,
         hints="VCC=5V from VBUS (or 3.3V with V3 tied to VCC). V3: 100nF to GND. UD+/UD- to USB D+/D-. TXD→MCU RX, RXD←MCU TX. "
               "DTR/RTS to ESP32 EN/IO0 auto-reset via 2x NPN or just 100nF (DTR→EN through cap)."))

# ============================================================ POWER
add(Part("ams1117-3.3", "AMS1117-3.3", "power", "1A LDO 3.3V, SOT-223, Vin 4.5–12V", F.sot223(),
         P(("1", "GND", GND), ("2", "VOUT", POUT), ("3", "VIN", PWR), ("4", "VOUT", POUT)),
         lcsc="C6186", price=0.12, power_w=0.5, value="3.3V", hints="10uF on VIN and VOUT (tantalum/MLCC). Dissipates (Vin-3.3)*I."))
add(Part("ap2112k-3.3", "AP2112K-3.3", "power", "600mA low-quiescent LDO 3.3V, SOT-23-5", F.sot23(5),
         P(("1", "VIN", PWR), ("2", "GND", GND), ("3", "EN", IN), ("4", "NC", NC), ("5", "VOUT", POUT)),
         lcsc="C51118", price=0.15, power_w=0.3, value="3.3V", hints="EN tied to VIN. 1uF on VIN, 1uF+ on VOUT."))
add(Part("mcp1700-3.3", "MCP1700-3302E", "power", "250mA ultra-low-Iq LDO 3.3V, SOT-23", F.sot23(3),
         P(("1", "GND", GND), ("2", "VOUT", POUT), ("3", "VIN", PWR)), lcsc="C39044", price=0.3, power_w=0.1, value="3.3V",
         hints="Battery designs. 1uF in/out."))
add(Part("tp4056", "TP4056 Li-ion charger", "power", "1A linear Li-ion charger, SOP-8", F.soic(8),
         P(("1", "TEMP", IN), ("2", "PROG", PAS), ("3", "GND", GND), ("4", "VCC", PWR), ("5", "BAT", POUT), ("6", "STDBY", OUT), ("7", "CHRG", OUT), ("8", "CE", IN)),
         lcsc="C16581", price=0.2, power_w=0.7,
         hints="VCC=5V. PROG resistor to GND sets current (1.2k=1A, 2k=580mA). TEMP to GND to disable. CE to VCC. CHRG/STDBY drive LEDs via 1k to VCC. BAT to battery + connector, 10uF."))
add(Part("mt3608", "MT3608 boost", "power", "Boost converter 2–24V in, up to 28V out, SOT-23-6", F.sot23(6),
         P(("1", "SW", BI), ("2", "GND", GND), ("3", "FB", IN), ("4", "EN", IN), ("5", "VIN", PWR), ("6", "NC", NC)),
         lcsc="C84817", price=0.15, power_w=0.3,
         hints="Inductor 22uH VIN→SW; Schottky SS34 SW→VOUT; FB divider (Vout=0.6*(1+R1/R2)); EN to VIN; 22uF in/out."))
add(Part("tps54302", "TPS54302 buck", "power", "3A synchronous buck 4.5–28V in, SOT-23-6", F.sot23(6),
         P(("1", "GND", GND), ("2", "SW", BI), ("3", "VIN", PWR), ("4", "FB", IN), ("5", "EN", IN), ("6", "BST", PAS)),
         lcsc="C169163", price=0.5, power_w=0.4,
         hints="BST: 100nF to SW. Inductor 4.7–10uH SW→VOUT. FB divider to 0.596V. 10uF in, 22uF out. EN to VIN via 100k."))
add(Part("mp1584", "MP1584EN buck", "power", "3A step-down 4.5–28V in, SOIC-8", F.soic(8),
         P(("1", "SW", BI), ("2", "EN", IN), ("3", "COMP", PAS), ("4", "FB", IN), ("5", "FREQ", PAS), ("6", "GND", GND), ("7", "VIN", PWR), ("8", "BST", PAS)),
         lcsc="C13996", price=0.5, power_w=0.5, hints="Adjustable buck; FB divider; 10uH inductor; SS34 not required (sync? no: needs SS34 SW→GND)."))
add(Part("lm7805", "L7805 5V regulator", "power", "1.5A linear 5V, TO-220", F.to220(),
         P(("1", "IN", PWR), ("2", "GND", GND), ("3", "OUT", POUT)), lcsc="C86205", price=0.25, power_w=1.5, value="5V",
         hints="Vin 7–24V. 330nF in, 100nF out. Hot at >500mA."))
add(Part("ao3400", "AO3400A N-MOSFET", "ic", "N-channel MOSFET 30V 5.7A, SOT-23, logic level", F.sot23(3),
         P(("1", "G", IN), ("2", "S", PAS), ("3", "D", PAS)), lcsc="C20917", price=0.05, power_w=0.1, ref_prefix="Q",
         hints="Low-side switch: S→GND, D→load, G←MCU via 100R, 10k G→S pull-down."))
add(Part("irlz44n", "IRLZ44N N-MOSFET", "ic", "N-channel MOSFET 55V 47A, TO-220, logic level", F.to220(),
         P(("1", "G", IN), ("2", "D", PAS), ("3", "S", PAS)), lcsc="C2833", price=0.6, power_w=1.0, ref_prefix="Q",
         hints="High-current loads (LED strips, heaters). Gate 100R + 10k pull-down."))
add(Part("drv8833", "DRV8833 motor driver", "ic", "Dual H-bridge 1.5A, 2.7–10.8V, TSSOP-16", F.tssop(16),
         auto(["nSLEEP", "AOUT1", "AISEN", "AOUT2", "BOUT2", "BISEN", "BOUT1", "nFAULT", "BIN1", "BIN2", "GND", "VCP", "VM", "VINT", "AIN2", "AIN1"]),
         lcsc="C50506", price=0.9, power_w=0.6,
         hints="VM = motor supply 2.7-10.8V with 10uF. VCP: 10nF to VM. VINT: 2.2uF to GND. AISEN/BISEN to GND. nSLEEP to logic high. AIN1/AIN2/BIN1/BIN2 from MCU PWM."))
add(Part("tb6612fng", "TB6612FNG motor driver", "ic", "Dual H-bridge 1.2A, SSOP-24", F.ssop(24),
         auto(["AO1", "AO1", "PGND1", "PGND1", "AO2", "AO2", "BO2", "BO2", "PGND2", "PGND2", "BO1", "BO1", "VM2", "VM3", "PWMB", "BIN2", "BIN1", "GND", "STBY", "VCC", "AIN1", "AIN2", "PWMA", "VM1"]),
         lcsc="C88224", price=1.2, power_w=0.5, hints="VM1-3 motor supply; VCC logic 3.3/5V; STBY high; PWMA/PWMB from MCU."))
add(Part("uln2003a", "ULN2003A", "ic", "7-channel Darlington driver, SOIC-16", F.soic(16),
         auto(["IN1", "IN2", "IN3", "IN4", "IN5", "IN6", "IN7", "GND", "COM", "OUT7", "OUT6", "OUT5", "OUT4", "OUT3", "OUT2", "OUT1"]),
         lcsc="C7512", price=0.15, power_w=0.3, hints="Drive relays / stepper coils. COM to load supply for flyback."))
add(Part("relay-srd-5v", "SRD-05VDC relay", "switch", "5V SPDT relay 10A, through-hole", F.relay_srd(),
         P(("1", "COIL1", PAS), ("2", "COIL2", PAS), ("3", "COM", PAS), ("4", "NO", PAS), ("5", "NC", PAS)),
         lcsc="C35449", price=0.5, power_w=0.4, ref_prefix="K",
         hints="Coil ~70mA: drive with AO3400 low-side + 1N4148 flyback across coil. Terminals: COM/NO/NC to screw terminal."))

# ============================================================ CONNECTORS
add(Part("usb-c-16p", "USB-C receptacle 16P", "connector", "USB Type-C 2.0 receptacle, 16 pin, mid-mount SMD", F.usb_c_16p(),
         P(("A1B12", "GND", GND), ("A4B9", "VBUS", PWR), ("B8", "SBU2", NC), ("A5", "CC1", BI), ("B7", "D-", BI), ("A6", "D+", BI),
           ("A7", "D-", BI), ("B6", "D+", BI), ("A8", "SBU1", NC), ("B5", "CC2", BI), ("B4A9", "VBUS", PWR), ("B1A12", "GND", GND),
           ("S1", "SHIELD", GND), ("S2", "SHIELD", GND), ("S3", "SHIELD", GND), ("S4", "SHIELD", GND)),
         lcsc="C165948", price=0.25, ref_prefix="J",
         hints="CC1 and CC2 EACH need a separate 5.1k pull-down to GND (two resistors). Tie A6+B6 (D+) together and A7+B7 (D-) together. Both VBUS pads to 5V net. Shield pads to GND."))
add(Part("barrel-jack", "DC barrel jack 5.5/2.1", "connector", "DC power jack DC-005, through-hole", F.barrel_jack(),
         P(("1", "VIN", PWR), ("2", "GND", GND), ("3", "SW", NC)), lcsc="C381118", price=0.2, ref_prefix="J",
         hints="Pin 1 centre pin (+), pin 2 sleeve (GND). Add SS34 reverse protection."))
add(Part("jst-ph-2", "JST-PH 2-pin (battery)", "connector", "JST PH 2.0mm 2-pin, LiPo battery", F.jst_ph(2),
         P(("1", "BAT+", PWR), ("2", "GND", GND)), lcsc="C131337", price=0.1, ref_prefix="J"))
add(Part("jst-ph-3", "JST-PH 3-pin", "connector", "JST PH 2.0mm 3-pin", F.jst_ph(3),
         P(("1", "1", PAS), ("2", "2", PAS), ("3", "3", PAS)), lcsc="C157929", price=0.1, ref_prefix="J"))
add(Part("jst-ph-4", "JST-PH 4-pin", "connector", "JST PH 2.0mm 4-pin", F.jst_ph(4),
         P(("1", "1", PAS), ("2", "2", PAS), ("3", "3", PAS), ("4", "4", PAS)), lcsc="C157930", price=0.12, ref_prefix="J"))
add(Part("qwiic", "Qwiic / STEMMA QT (JST-SH 4)", "connector", "JST SH 1.0mm 4-pin I2C connector", F.jst_sh_smd(4),
         P(("1", "GND", GND), ("2", "3V3", PWR), ("3", "SDA", BI), ("4", "SCL", BI), ("S1", "SHIELD", NC), ("S2", "SHIELD", NC)),
         lcsc="C160404", price=0.15, ref_prefix="J", hints="Order: GND, 3V3, SDA, SCL"))
for n in (2, 3, 4, 5, 6, 8, 10):
    add(Part(f"header-1x{n}", f"Pin header 1x{n}", "connector", f"2.54mm pin header 1x{n}", F.header(n),
             P(*[(str(i + 1), str(i + 1), PAS) for i in range(n)]), lcsc="C124378", price=0.05, ref_prefix="J",
             hints="generic; name pins in purpose"))
add(Part("header-2x5", "Pin header 2x5 (JTAG/SWD)", "connector", "2.54mm box header 2x5", F.header(5, 2),
         P(*[(str(i + 1), str(i + 1), PAS) for i in range(10)]), lcsc="C2337", price=0.1, ref_prefix="J"))
add(Part("header-2x3-icsp", "ICSP header 2x3", "connector", "AVR ICSP 2x3 header", F.header(3, 2),
         P(("1", "MISO", BI), ("2", "VCC", PWR), ("3", "SCK", BI), ("4", "MOSI", BI), ("5", "RESET", BI), ("6", "GND", GND)),
         lcsc="C2337", price=0.08, ref_prefix="J"))
add(Part("screw-2", "Screw terminal 2-pin", "connector", "5.08mm screw terminal 2P", F.screw_terminal(2),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C8465", price=0.15, ref_prefix="J"))
add(Part("screw-3", "Screw terminal 3-pin", "connector", "5.08mm screw terminal 3P", F.screw_terminal(3),
         P(("1", "1", PAS), ("2", "2", PAS), ("3", "3", PAS)), lcsc="C8270", price=0.2, ref_prefix="J"))
add(Part("microsd", "microSD slot", "connector", "microSD push-push socket (SPI mode)", F.microsd_slot(),
         P(("1", "DAT2", NC), ("2", "CS/DAT3", IN), ("3", "CMD/MOSI", IN), ("4", "VDD", PWR), ("5", "CLK", IN), ("6", "VSS", GND),
           ("7", "DAT0/MISO", OUT), ("8", "DAT1", NC), ("9", "CD", OUT), ("S1", "SHIELD", GND), ("S2", "SHIELD", GND), ("S3", "SHIELD", GND), ("S4", "SHIELD", GND)),
         lcsc="C91145", price=0.3, ref_prefix="J", hints="SPI: CS, MOSI, MISO, CLK. 10k pull-ups on CS/MISO optional. 100nF+10uF on VDD."))
add(Part("servo-header", "Servo header 1x3", "connector", "Servo connector: GND, VCC, SIGNAL", F.header(3),
         P(("1", "SIG", IN), ("2", "VCC", PWR), ("3", "GND", GND)), lcsc="C124378", price=0.05, ref_prefix="J"))
add(Part("oled-header", "OLED SSD1306 header", "connector", "4-pin header for 0.96\" I2C OLED: GND VCC SCL SDA", F.header(4),
         P(("1", "GND", GND), ("2", "VCC", PWR), ("3", "SCL", IN), ("4", "SDA", BI)), lcsc="C124378", price=0.05, ref_prefix="J"))
add(Part("dht22-header", "DHT22 header", "connector", "4-pin header for DHT22/AM2302 sensor", F.header(4),
         P(("1", "VDD", PWR), ("2", "DATA", BI), ("3", "NC", NC), ("4", "GND", GND)), lcsc="C124378", price=0.05, ref_prefix="J",
         hints="DATA needs 10k pull-up"))
add(Part("hcsr04-header", "HC-SR04 header", "connector", "4-pin header for ultrasonic module: VCC TRIG ECHO GND", F.header(4),
         P(("1", "VCC", PWR), ("2", "TRIG", IN), ("3", "ECHO", OUT), ("4", "GND", GND)), lcsc="C124378", price=0.05, ref_prefix="J",
         hints="5V module; ECHO is 5V — divide to 3.3V (1k/2k) for ESP32"))
add(Part("gps-header", "GPS NEO-6M header", "connector", "4-pin header for GPS module: VCC RX TX GND", F.header(4),
         P(("1", "VCC", PWR), ("2", "RX", IN), ("3", "TX", OUT), ("4", "GND", GND)), lcsc="C124378", price=0.05, ref_prefix="J"))
add(Part("battery-18650", "18650 battery holder", "connector", "Single 18650 cell holder, THT", F.battery_holder_18650(),
         P(("1", "+", PWR), ("2", "-", GND)), lcsc="C5290", price=0.4, ref_prefix="BT", hints="Very large (77mm) — board must be > 85mm wide"))
add(Part("cr2032", "CR2032 holder", "connector", "CR2032 coin cell holder SMD", F.coin_cell_cr2032(),
         P(("1", "+", PWR), ("2", "-", GND)), lcsc="C70377", price=0.2, ref_prefix="BT"))

# ============================================================ SENSORS
add(Part("sht31", "SHT31-DIS", "sensor", "Temperature/humidity ±2%RH, I2C, DFN-8", F.dfn(8, 0.5, 2.5, 2.5),
         P(("1", "SDA", BI), ("2", "ADDR", IN), ("3", "ALERT", OUT), ("4", "SCL", IN), ("5", "VDD", PWR), ("6", "nRESET", IN), ("7", "R", NC), ("8", "VSS", GND)),
         lcsc="C93085", price=2.5, power_w=0.002, hints="ADDR to GND (0x44). nRESET to VDD. 100nF. I2C pull-ups 4.7k."))
add(Part("bme280", "BME280", "sensor", "Temp/humidity/pressure, I2C/SPI, LGA-8", F.dfn(8, 0.65, 2.5, 2.5, name="LGA"),
         P(("1", "GND", GND), ("2", "CSB", IN), ("3", "SDI/SDA", BI), ("4", "SCK/SCL", IN), ("5", "SDO", BI), ("6", "VDDIO", PWR), ("7", "GND", GND), ("8", "VDD", PWR)),
         lcsc="C92489", price=2.2, power_w=0.001, hints="I2C: CSB to VDDIO, SDO to GND (addr 0x76). 100nF on VDD and VDDIO."))
add(Part("mpu6050", "MPU-6050", "sensor", "6-axis accel+gyro, I2C, QFN-24 4x4", F.qfn(24, 0.5, 4.0, 0.0),
         [("1", "CLKIN", IN), ("2", "NC", NC), ("3", "NC", NC), ("4", "NC", NC), ("5", "NC", NC), ("6", "AUX_DA", BI), ("7", "AUX_CL", BI), ("8", "VLOGIC", PWR),
          ("9", "AD0", IN), ("10", "REGOUT", POUT), ("11", "FSYNC", IN), ("12", "INT", OUT), ("13", "VDD", PWR), ("14", "NC", NC), ("15", "NC", NC), ("16", "NC", NC),
          ("17", "NC", NC), ("18", "GND", GND), ("19", "NC", NC), ("20", "CPOUT", PAS), ("21", "NC", NC), ("22", "NC", NC), ("23", "SCL", IN), ("24", "SDA", BI)],
         lcsc="C24112", price=1.8, power_w=0.012,
         hints="VDD & VLOGIC to 3V3 with 100nF each. REGOUT 100nF to GND. CPOUT 2.2nF to GND. AD0 to GND. CLKIN/FSYNC to GND. INT to MCU GPIO."))
add(Part("ds18b20", "DS18B20", "sensor", "1-Wire digital temperature sensor, TO-92", F.to92_wide(),
         P(("1", "GND", GND), ("2", "DQ", BI), ("3", "VDD", PWR)), lcsc="C376006", price=0.9, hints="4.7k pull-up DQ→VDD"))
add(Part("ina219", "INA219", "sensor", "Current/power monitor, I2C, SOT-23-8", F.sot23(8),
         P(("1", "IN+", IN), ("2", "IN-", IN), ("3", "GND", GND), ("4", "VS", PWR), ("5", "SCL", IN), ("6", "SDA", BI), ("7", "A0", IN), ("8", "A1", IN)),
         lcsc="C87469", price=0.9, hints="0.1R 1206 shunt between IN+ and IN-. A0/A1 to GND. 100nF."))
add(Part("ads1115", "ADS1115", "sensor", "16-bit 4-ch I2C ADC, TSSOP-10", F.tssop(10),
         P(("1", "ADDR", IN), ("2", "ALERT", OUT), ("3", "GND", GND), ("4", "AIN0", IN), ("5", "AIN1", IN), ("6", "AIN2", IN), ("7", "AIN3", IN), ("8", "VDD", PWR), ("9", "SDA", BI), ("10", "SCL", IN)),
         lcsc="C37593", price=1.5, hints="ADDR to GND (0x48). 100nF VDD."))
add(Part("shunt-1206", "Shunt resistor 1206", "passive", "Current sense resistor 0.1R 1W 1206", F.chip("1206"),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C25321", price=0.05, value="0.1R", ref_prefix="R"))
add(Part("ntc-0603", "NTC thermistor 0603", "sensor", "10k NTC thermistor 0603", F.chip("0603"),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C13564", price=0.03, value="10k NTC", ref_prefix="TH", hints="divider with 10k to ADC"))
add(Part("ldr-header", "Photoresistor (LDR) header", "sensor", "2-pin for GL5528 LDR", F.header(2),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C124378", price=0.05, ref_prefix="R", hints="divider with 10k to ADC"))
add(Part("pir-header", "PIR sensor header", "connector", "3-pin for HC-SR501 PIR: VCC OUT GND", F.header(3),
         P(("1", "VCC", PWR), ("2", "OUT", OUT), ("3", "GND", GND)), lcsc="C124378", price=0.05, ref_prefix="J", hints="5V module, 3.3V logic out OK"))
add(Part("tsop-ir", "IR receiver TSOP38238", "sensor", "38kHz IR receiver, THT", F.to92_wide(),
         P(("1", "OUT", OUT), ("2", "GND", GND), ("3", "VS", PWR)), lcsc="C51330", price=0.3, hints="100R + 4.7uF supply filter"))
add(Part("hall-a3144", "Hall sensor A3144", "sensor", "Hall-effect switch, TO-92", F.to92_wide(),
         P(("1", "VCC", PWR), ("2", "GND", GND), ("3", "OUT", OUT)), lcsc="C8220", price=0.15, hints="10k pull-up on OUT"))
add(Part("mic-header", "MEMS mic (INMP441) header", "connector", "6-pin header for I2S mic: VDD GND SD WS SCK L/R", F.header(6),
         P(("1", "VDD", PWR), ("2", "GND", GND), ("3", "SD", OUT), ("4", "WS", IN), ("5", "SCK", IN), ("6", "L/R", IN)),
         lcsc="C124378", price=0.05, ref_prefix="J"))

# ============================================================ OTHER ICs
add(Part("ds3231", "DS3231 RTC", "ic", "Precision I2C RTC with TCXO, SOIC-16W", F.soic(16, wide=True),
         auto(["32KHZ", "VCC", "INT/SQW", "RST", "NC", "NC", "NC", "NC", "NC", "NC", "NC", "NC", "GND", "VBAT", "SDA", "SCL"]),
         lcsc="C9866", price=1.5, hints="VBAT to CR2032 +. 100nF VCC. RST 10k pull-up optional."))
add(Part("24lc256", "24LC256 EEPROM", "ic", "256Kbit I2C EEPROM, SOIC-8", F.soic(8),
         auto(["A0", "A1", "A2", "VSS", "SDA", "SCL", "WP", "VCC"]), lcsc="C7448", price=0.3, hints="A0-A2 & WP to GND"))
add(Part("w25q128", "W25Q128 SPI flash", "ic", "128Mbit SPI NOR flash, SOIC-8", F.soic(8),
         auto(["CS", "DO", "WP", "GND", "DI", "CLK", "HOLD", "VCC"]), lcsc="C97521", price=0.6, hints="WP and HOLD 10k to VCC"))
add(Part("lm358", "LM358 op-amp", "ic", "Dual op-amp, SOIC-8", F.soic(8),
         auto(["OUT1", "IN1-", "IN1+", "GND", "IN2+", "IN2-", "OUT2", "VCC"]), lcsc="C7950", price=0.1))
add(Part("lm393", "LM393 comparator", "ic", "Dual comparator, SOIC-8", F.soic(8),
         auto(["OUT1", "IN1-", "IN1+", "GND", "IN2+", "IN2-", "OUT2", "VCC"]), lcsc="C7955", price=0.1))
add(Part("mcp3008", "MCP3008 ADC", "ic", "10-bit 8-ch SPI ADC, SOIC-16", F.soic(16),
         auto(["CH0", "CH1", "CH2", "CH3", "CH4", "CH5", "CH6", "CH7", "DGND", "CS", "DIN", "DOUT", "CLK", "AGND", "VREF", "VDD"]), lcsc="C129793", price=1.8))
add(Part("mcp4725", "MCP4725 DAC", "ic", "12-bit I2C DAC, SOT-23-6", F.sot23(6),
         P(("1", "VOUT", OUT), ("2", "VSS", GND), ("3", "VDD", PWR), ("4", "SDA", BI), ("5", "SCL", IN), ("6", "A0", IN)), lcsc="C61423", price=0.9))
add(Part("hx711", "HX711 load-cell ADC", "ic", "24-bit ADC for bridge sensors, SOP-16", F.soic(16),
         auto(["VSUP", "BASE", "AVDD", "VFB", "AGND", "VBG", "INA-", "INA+", "INB-", "INB+", "PD_SCK", "DOUT", "XO", "XI", "RATE", "DVDD"]),
         lcsc="C45471", price=0.5, hints="VSUP=DVDD=3V3-5V; AVDD via 8.2k/20k divider on VFB; XI to GND; RATE to GND (10Hz)"))
add(Part("max6675", "MAX6675 thermocouple", "ic", "K-type thermocouple to SPI, SOIC-8", F.soic(8),
         auto(["GND", "T-", "T+", "VCC", "SCK", "CS", "SO", "NC"]), lcsc="C13767", price=1.5, hints="T+/T- to screw terminal; 100nF VCC"))
add(Part("pca9685", "PCA9685 PWM driver", "ic", "16-ch 12-bit I2C PWM (servos/LEDs), TSSOP-28", F.tssop(28),
         auto(["A0", "A1", "A2", "A3", "A4", "LED0", "LED1", "LED2", "LED3", "LED4", "LED5", "LED6", "LED7", "GND", "LED8", "LED9", "LED10", "LED11", "LED12", "LED13", "LED14", "LED15", "OE", "A5", "EXTCLK", "SCL", "SDA", "VDD"]),
         lcsc="C28369", price=1.2, hints="A0-A5 to GND (0x40); OE to GND; EXTCLK to GND; 100nF"))
add(Part("mcp23017", "MCP23017 IO expander", "ic", "16-bit I2C GPIO expander, SOIC-28W", F.soic(28, wide=True),
         auto(["GPB0", "GPB1", "GPB2", "GPB3", "GPB4", "GPB5", "GPB6", "GPB7", "VDD", "VSS", "NC", "SCL", "SDA", "NC", "A0", "A1", "A2", "RESET", "INTB", "INTA", "GPA0", "GPA1", "GPA2", "GPA3", "GPA4", "GPA5", "GPA6", "GPA7"]),
         lcsc="C47023", price=1.1, hints="RESET 10k pull-up; A0-A2 to GND"))
add(Part("txs0108e", "TXS0108E level shifter", "ic", "8-bit bidirectional level shifter, TSSOP-20", F.tssop(20),
         auto(["A1", "VCCA", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "OE", "GND", "B8", "B7", "B6", "B5", "B4", "B3", "B2", "B1", "VCCB"]),
         lcsc="C17206", price=0.6, hints="VCCA=3V3 side, VCCB=5V side, OE 10k pull-up to VCCA"))
add(Part("74hc595", "74HC595 shift register", "ic", "8-bit serial-in parallel-out, SOIC-16", F.soic(16),
         auto(["QB", "QC", "QD", "QE", "QF", "QG", "QH", "GND", "QH'", "SRCLR", "SRCLK", "RCLK", "OE", "SER", "QA", "VCC"]),
         lcsc="C5947", price=0.1, hints="SRCLR to VCC, OE to GND"))
add(Part("max485", "MAX485 RS-485", "ic", "RS-485 transceiver, SOIC-8", F.soic(8),
         auto(["RO", "RE", "DE", "DI", "GND", "A", "B", "VCC"]), lcsc="C8963", price=0.3, hints="RE+DE tied to MCU direction pin; 120R A-B termination; A/B to screw terminal"))
add(Part("mcp2515", "MCP2515 CAN controller", "ic", "SPI CAN controller, SOIC-18", F.soic(18),
         auto(["TXCAN", "RXCAN", "CLKOUT", "TX0RTS", "TX1RTS", "TX2RTS", "OSC2", "OSC1", "VSS", "RX1BF", "RX0BF", "INT", "SCK", "SI", "SO", "CS", "RESET", "VDD"]),
         lcsc="C9004", price=1.5, hints="8MHz/16MHz crystal on OSC1/OSC2 + 22pF; TX0-2RTS/RX0-1BF to VDD; RESET 10k to VDD; pair with TJA1050"))
add(Part("tja1050", "TJA1050 CAN transceiver", "ic", "High-speed CAN transceiver, SOIC-8", F.soic(8),
         auto(["TXD", "GND", "VCC", "RXD", "VREF", "CANL", "CANH", "S"]), lcsc="C13246", price=0.5, hints="5V; S to GND; 120R CANH-CANL"))
add(Part("ttp223", "TTP223 touch", "ic", "Capacitive touch button IC, SOT-23-6", F.sot23(6),
         P(("1", "Q", OUT), ("2", "VDD", PWR), ("3", "I", IN), ("4", "AHLB", IN), ("5", "VSS", GND), ("6", "TOG", IN)),
         lcsc="C80757", price=0.1, hints="I to touch pad (copper pad ~10mm); AHLB/TOG to GND; 100nF"))
add(Part("pam8403", "PAM8403 audio amp", "ic", "3W class-D stereo amp, SOP-16", F.soic(16),
         auto(["+OUT_L", "PGND", "-OUT_L", "PVDD", "MUTE", "VDD", "INL", "GND", "INR", "VREF", "NC", "SHDN", "PVDD", "-OUT_R", "PGND", "+OUT_R"]),
         lcsc="C113368", price=0.3, power_w=0.5, hints="5V; MUTE/SHDN to VDD; 1uF VREF; inputs via 1uF; outputs to speaker terminals"))
add(Part("pc817", "PC817 optocoupler", "ic", "Optocoupler, SOP-4", F.soic(8),
         P(("1", "A", IN), ("2", "K", PAS), ("3", "E", PAS), ("4", "C", PAS), ("5", "NC", NC), ("6", "NC", NC), ("7", "NC", NC), ("8", "NC", NC)),
         lcsc="C106865", price=0.08))

# ============================================================ CRYSTALS / SWITCHES / MISC
add(Part("xtal-hc49", "Crystal HC-49S", "crystal", "SMD crystal 8/16MHz HC-49S", F.crystal_hc49_smd(),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C12674", price=0.1, value="16MHz", ref_prefix="Y", hints="2x 22pF load caps to GND"))
add(Part("xtal-3225", "Crystal 3225 4-pin", "crystal", "SMD crystal 3.2x2.5mm, 4 pad", F.crystal_3225(),
         P(("1", "1", PAS), ("2", "GND", GND), ("3", "2", PAS), ("4", "GND", GND)), lcsc="C9002", price=0.15, value="8MHz", ref_prefix="Y",
         hints="pins 1 & 3 are the crystal; 2 & 4 GND; 2x 20pF"))
add(Part("xtal-32k", "Crystal 32.768kHz", "crystal", "SMD 32.768kHz 3215", F.crystal_3215(),
         P(("1", "1", PAS), ("2", "2", PAS)), lcsc="C32346", price=0.15, value="32.768kHz", ref_prefix="Y"))
add(Part("sw-tact", "Tactile switch 6x6 THT", "switch", "6x6mm tactile push button, through-hole", F.tact_switch_6x6(),
         P(("1", "1", PAS), ("2", "1", PAS), ("3", "2", PAS), ("4", "2", PAS)), lcsc="C127509", price=0.03, ref_prefix="SW",
         hints="pins 1&2 are one side, 3&4 the other: connect pin 1 to signal and pin 3 to GND"))
add(Part("sw-tact-smd", "Tactile switch SMD", "switch", "4.5x4.5mm SMD tactile switch", F.tact_switch_smd(),
         P(("1", "1", PAS), ("2", "1", PAS), ("3", "2", PAS), ("4", "2", PAS)), lcsc="C318884", price=0.04, ref_prefix="SW",
         hints="pins 1&2 one side, 3&4 other: connect pin 1 to signal, pin 3 to GND"))
add(Part("sw-slide", "Slide switch SPDT", "switch", "SS12D00 slide switch, through-hole", F.slide_switch(),
         P(("1", "1", PAS), ("2", "COM", PAS), ("3", "3", PAS), ("S1", "M", NC), ("S2", "M", NC)), lcsc="C431540", price=0.08, ref_prefix="SW",
         hints="power switch: COM (pin 2) in series with supply"))
add(Part("encoder-ec11", "Rotary encoder EC11", "switch", "Rotary encoder with push switch", F.rotary_encoder(),
         P(("A", "A", OUT), ("C", "C", GND), ("B", "B", OUT), ("S1", "SW1", PAS), ("S2", "SW2", PAS), ("M1", "M", NC), ("M2", "M", NC)),
         lcsc="C470754", price=0.4, ref_prefix="SW", hints="C to GND; A/B to GPIO with 10k pull-ups; SW1 to GPIO, SW2 to GND"))
add(Part("pot-10k", "Potentiometer 10k", "passive", "3386P trimmer 10k", F.potentiometer(),
         P(("1", "1", PAS), ("2", "W", PAS), ("3", "3", PAS)), lcsc="C118942", price=0.2, value="10k", ref_prefix="RV"))
add(Part("buzzer", "Passive buzzer 12mm", "switch", "12mm piezo/magnetic buzzer THT", F.buzzer_12mm(),
         P(("1", "+", PAS), ("2", "-", PAS)), lcsc="C96094", price=0.2, ref_prefix="BZ", power_w=0.1,
         hints="drive with AO3400 or directly from GPIO via 100R"))
add(Part("mount-m3", "Mounting hole M3", "mechanical", "3.2mm NPTH mounting hole", F.mounting_hole_m3(),
         P(("1", "1", NC)), price=0.0, ref_prefix="H"))
add(Part("testpoint", "Test point", "mechanical", "1.5mm SMD test pad", F.test_point(),
         P(("1", "1", PAS)), price=0.0, ref_prefix="TP"))


def catalog_prompt() -> str:
    """Compact catalog listing for the LLM."""
    lines = []
    cats = {}
    for p in CATALOG.values():
        cats.setdefault(p.category, []).append(p)
    for cat, parts in cats.items():
        lines.append(f"\n### {cat}")
        for p in parts:
            pins = ",".join(f"{n}:{nm}" for n, nm, t in p.pins)
            if p.id.startswith(("r-", "c-")) and p.id != "c-elec-6.3":
                pins = "1,2"
            elif p.id.startswith("header-1x"):
                pins = "1..%d" % len(p.pins)
            s = f"- `{p.id}` {p.name} [{p.footprint.name}] pins({pins})"
            if p.hints:
                s += f" — {p.hints}"
            lines.append(s)
    return "\n".join(lines)
