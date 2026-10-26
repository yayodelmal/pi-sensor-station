"""Sensor access without a GPIO polling loop."""

import time
from pathlib import Path


class SensorDisconnected(RuntimeError):
    """The sensor device is absent rather than returning an invalid reading."""


def crc8(data):
    crc = 0xFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def decode_sht31(data):
    if len(data) != 6 or crc8(data[:2]) != data[2] or crc8(data[3:5]) != data[5]:
        raise ValueError("SHT31: invalid length or CRC")
    temperature = -45 + 175 * int.from_bytes(data[:2], "big") / 65535
    humidity = 100 * int.from_bytes(data[3:5], "big") / 65535
    if not -40 <= temperature <= 125:
        raise ValueError("SHT31: temperature outside sensor range")
    return {"temperature": round(temperature, 2), "humidity": round(humidity, 2)}


class SHT31:
    def __init__(self, bus=1, address=0x44):
        self.bus = bus
        self.address = address

    def read(self):
        from smbus2 import SMBus, i2c_msg

        # Single-shot, high repeatability, without clock stretching.
        with SMBus(self.bus) as bus:
            bus.i2c_rdwr(i2c_msg.write(self.address, [0x24, 0x00]))
            time.sleep(0.02)
            message = i2c_msg.read(self.address, 6)
            bus.i2c_rdwr(message)
        return decode_sht31(bytes(message))


def decode_ds18b20(text):
    lines = text.strip().splitlines()
    if len(lines) != 2 or not lines[0].strip().endswith("YES") or "t=" not in lines[1]:
        raise ValueError("DS18B20: missing temperature or failed CRC")
    temperature = int(lines[1].split("t=", 1)[1]) / 1000
    if not -55 <= temperature <= 125 or temperature == 85.0:
        raise ValueError("DS18B20: temperature outside sensor range")
    return {"temperature": temperature}


class DS18B20:
    def __init__(self, device_id="", root="/sys/bus/w1/devices"):
        self.root = Path(root)
        if device_id and (not device_id.startswith("28-") or any(c not in "0123456789abcdefABCDEF-" for c in device_id)):
            raise ValueError("DS18B20_ID must be a 28-... device identifier")
        self.device_id = device_id

    def read(self):
        if self.device_id:
            path = self.root / self.device_id / "w1_slave"
        else:
            devices = sorted(self.root.glob("28-*/w1_slave"))
            if not devices:
                raise SensorDisconnected("DS18B20 device not found")
            if len(devices) > 1:
                raise RuntimeError("Expected one DS18B20; connect it or set DS18B20_ID explicitly")
            path = devices[0]
        try:
            return decode_ds18b20(path.read_text())
        except FileNotFoundError as error:
            raise SensorDisconnected("DS18B20 device not found") from error
