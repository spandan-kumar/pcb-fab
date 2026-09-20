"""Synthetic design used for engine tests (no LLM)."""
from etch.catalog import CATALOG
from etch.model import Board, Component, Net


def make_board() -> Board:
    b = Board(width=50, height=40, name="TESTNODE")
    comps = [
        ("U1", "esp32-wroom-32e", ""), ("U2", "ams1117-3.3", ""), ("J1", "usb-c-16p", ""), ("U3", "sht31", ""),
        ("C1", "c-0805", "10uF"), ("C2", "c-0805", "10uF"), ("C3", "c-0603", "100nF"), ("C4", "c-0603", "100nF"),
        ("R1", "r-0603", "10k"), ("R2", "r-0603", "5.1k"), ("R3", "r-0603", "5.1k"), ("R4", "r-0603", "4.7k"), ("R5", "r-0603", "4.7k"),
        ("R6", "r-0603", "1k"), ("D1", "led-0603", "green"), ("SW1", "sw-tact-smd", "BOOT"), ("SW2", "sw-tact-smd", "RESET"),
        ("J2", "header-1x4", "UART"), ("H1", "mount-m3", ""), ("H2", "mount-m3", ""), ("H3", "mount-m3", ""), ("H4", "mount-m3", ""),
    ]
    for ref, pid, val in comps:
        b.components.append(Component(ref, CATALOG[pid], val))
    nets = [
        Net("GND", [("U1", "1"), ("U1", "15"), ("U1", "38"), ("U1", "39"), ("U2", "1"), ("J1", "A1B12"), ("J1", "B1A12"), ("J1", "S1"), ("J1", "S2"), ("J1", "S3"), ("J1", "S4"),
                    ("U3", "8"), ("C1", "2"), ("C2", "2"), ("C3", "2"), ("C4", "2"), ("R2", "2"), ("R3", "2"), ("D1", "1"), ("SW1", "3"), ("SW2", "3"), ("J2", "4"), ("U3", "2")], "gnd"),
        Net("VBUS", [("J1", "A4B9"), ("J1", "B4A9"), ("U2", "3"), ("C1", "1")], "power", 5.0, 500),
        Net("3V3", [("U2", "2"), ("U2", "4"), ("U1", "2"), ("C2", "1"), ("C3", "1"), ("U3", "5"), ("C4", "1"), ("R1", "1"), ("R4", "1"), ("R5", "1"), ("J2", "1"), ("U3", "6")], "power", 3.3, 600),
        Net("CC1", [("J1", "A5"), ("R2", "1")]), Net("CC2", [("J1", "B5"), ("R3", "1")]),
        Net("EN", [("U1", "3"), ("R1", "2"), ("SW2", "1")]),
        Net("IO0", [("U1", "25"), ("SW1", "1")]),
        Net("SDA", [("U1", "33"), ("U3", "1"), ("R4", "2")]),
        Net("SCL", [("U1", "36"), ("U3", "4"), ("R5", "2")]),
        Net("LED", [("U1", "24"), ("R6", "1")]), Net("LED_A", [("R6", "2"), ("D1", "2")]),
        Net("TXD0", [("U1", "35"), ("J2", "2")]), Net("RXD0", [("U1", "34"), ("J2", "3")]),
    ]
    b.nets = nets
    return b
