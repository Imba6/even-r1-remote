"""Resolve a previously selected ring through the Windows Bluetooth cache.

Cache identity does not establish that a device is present or connected. This
fallback only supplies a verified native identity for a subsequent connection
attempt when the ring is absent from a fresh advertisement scan.
"""

import asyncio
import logging
import re
import sys

from bleak.backends.device import BLEDevice

logger = logging.getLogger(__name__)
_LOOKUP_TIMEOUT = 5.0
_MAC_ADDRESS = re.compile(
    r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|(?:[0-9a-f]{2}-){5}[0-9a-f]{2}",
    re.IGNORECASE,
)


def _load_bluetooth_le_device():
    """Import WinRT only after the platform and address have been checked."""
    from winrt.windows.devices.bluetooth import BluetoothLEDevice

    return BluetoothLEDevice


async def cached_ring(address: str) -> BLEDevice | None:
    """Return the native cached R1 identity for a known address, if available.

    The returned ``details`` is Windows' actual ``DeviceInformation`` object.
    No advertisement, signal strength, connection status, or name is fabricated.
    Ordinary cache failures return ``None``; task cancellation is preserved.
    """
    if sys.platform != "win32":
        logger.debug("Windows cached ring lookup is unavailable on this platform")
        return None
    if not isinstance(address, str) or _MAC_ADDRESS.fullmatch(address) is None:
        logger.warning("Windows cached ring lookup requires a valid Bluetooth address")
        return None

    expected_address = int(address.replace(":", "").replace("-", ""), 16)
    native = None
    try:
        device_type = _load_bluetooth_le_device()
        async with asyncio.timeout(_LOOKUP_TIMEOUT):
            native = await device_type.from_bluetooth_address_async(expected_address)
        if native is None:
            logger.info("Windows has no cached Bluetooth identity for the saved ring")
            return None
        if native.bluetooth_address != expected_address:
            logger.warning("Windows cached Bluetooth identity has an unexpected address")
            return None
        name = native.name
        if not isinstance(name, str) or not name.upper().startswith("EVEN R1"):
            logger.info("Windows cached Bluetooth identity is not named EVEN R1")
            return None
        information = native.device_information
        if information is None:
            logger.info("Windows cached Bluetooth identity has no device information")
            return None
        canonical_address = ":".join(
            f"{expected_address:012X}"[offset : offset + 2]
            for offset in range(0, 12, 2)
        )
        return BLEDevice(canonical_address, name, information)
    except TimeoutError:
        logger.warning("Windows cached ring lookup timed out")
        return None
    except Exception:
        logger.warning("Windows cached ring lookup is unavailable", exc_info=True)
        return None
    finally:
        if native is not None:
            try:
                native.close()
            except Exception:
                logger.warning("Could not close Windows cached Bluetooth device", exc_info=True)
