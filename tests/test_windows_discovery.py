import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bleak.backends.device import BLEDevice

from even_r1 import windows_discovery

ADDRESS = "AA:BB:CC:DD:EE:FF"
ADDRESS_NUMBER = 0xAABBCCDDEEFF


@pytest.fixture
def native_cache(monkeypatch):
    native = SimpleNamespace(
        bluetooth_address=ADDRESS_NUMBER,
        name="EVEN R1_123456",
        device_information=object(),
        close=Mock(),
    )
    api = SimpleNamespace(from_bluetooth_address_async=AsyncMock(return_value=native))
    loader = Mock(return_value=api)
    monkeypatch.setattr(windows_discovery.sys, "platform", "win32")
    monkeypatch.setattr(windows_discovery, "_load_bluetooth_le_device", loader)
    return SimpleNamespace(native=native, api=api, loader=loader)


@pytest.mark.parametrize("address", [ADDRESS, ADDRESS.lower(), "aa-bb-cc-dd-ee-ff"])
async def test_cached_ring_uses_verified_native_identity(native_cache, address):
    device = await windows_discovery.cached_ring(address)

    assert isinstance(device, BLEDevice)
    assert device.address == ADDRESS
    assert device.name == native_cache.native.name
    assert device.details is native_cache.native.device_information
    native_cache.api.from_bluetooth_address_async.assert_awaited_once_with(ADDRESS_NUMBER)
    native_cache.native.close.assert_called_once_with()


async def test_cached_ring_accepts_case_insensitive_native_name(native_cache):
    native_cache.native.name = "even r1_123456"

    device = await windows_discovery.cached_ring(ADDRESS)

    assert device.name == "even r1_123456"
    native_cache.native.close.assert_called_once_with()


async def test_no_native_cache_identity_returns_none(native_cache):
    native_cache.api.from_bluetooth_address_async.return_value = None

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native_cache.native.close.assert_not_called()


async def test_address_mismatch_rejected_and_closed(native_cache):
    native_cache.native.bluetooth_address = ADDRESS_NUMBER - 1

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native_cache.native.close.assert_called_once_with()


@pytest.mark.parametrize("name", [None, "", "R1", "OTHER RING", " EVEN R1", 123])
async def test_non_r1_native_identity_rejected_and_closed(native_cache, name):
    native_cache.native.name = name

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native_cache.native.close.assert_called_once_with()


async def test_missing_device_information_rejected_and_closed(native_cache):
    native_cache.native.device_information = None

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native_cache.native.close.assert_called_once_with()


async def test_non_windows_does_not_import_winrt(native_cache, monkeypatch):
    monkeypatch.setattr(windows_discovery.sys, "platform", "linux")

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native_cache.loader.assert_not_called()
    native_cache.api.from_bluetooth_address_async.assert_not_called()


@pytest.mark.parametrize(
    "address", [None, 123, "", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:GG",
                "AA:BB-CC:DD:EE:FF", "AABBCCDDEEFF", " AA:BB:CC:DD:EE:FF"]
)
async def test_invalid_address_does_not_import_winrt(native_cache, address):
    assert await windows_discovery.cached_ring(address) is None
    native_cache.loader.assert_not_called()
    native_cache.api.from_bluetooth_address_async.assert_not_called()


async def test_missing_winrt_returns_none_and_logs(native_cache, caplog):
    native_cache.loader.side_effect = ImportError("WinRT unavailable")

    assert await windows_discovery.cached_ring(ADDRESS) is None
    assert "cached ring lookup is unavailable" in caplog.text


async def test_native_lookup_error_returns_none_and_logs(native_cache, caplog):
    native_cache.api.from_bluetooth_address_async.side_effect = OSError("Adapter unavailable")

    assert await windows_discovery.cached_ring(ADDRESS) is None
    assert "cached ring lookup is unavailable" in caplog.text
    native_cache.native.close.assert_not_called()


async def test_native_identity_read_error_still_closes(native_cache):
    class Native:
        bluetooth_address = ADDRESS_NUMBER
        close = Mock()

        @property
        def name(self):
            raise OSError("Device disappeared")

    native = Native()
    native_cache.api.from_bluetooth_address_async.return_value = native

    assert await windows_discovery.cached_ring(ADDRESS) is None
    native.close.assert_called_once_with()


async def test_native_cleanup_error_does_not_escape(native_cache, caplog):
    native_cache.native.close.side_effect = OSError("Close failed")

    device = await windows_discovery.cached_ring(ADDRESS)

    assert device.address == ADDRESS
    assert "Could not close Windows cached Bluetooth device" in caplog.text


async def test_lookup_timeout_is_bounded_and_cancels_lookup(native_cache, monkeypatch, caplog):
    cancelled = asyncio.Event()

    async def pending_lookup(address):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    native_cache.api.from_bluetooth_address_async.side_effect = pending_lookup
    monkeypatch.setattr(windows_discovery, "_LOOKUP_TIMEOUT", 0.01)

    assert await windows_discovery.cached_ring(ADDRESS) is None
    assert cancelled.is_set()
    assert "cached ring lookup timed out" in caplog.text


async def test_lookup_cancellation_propagates(native_cache):
    entered = asyncio.Event()

    async def pending_lookup(address):
        entered.set()
        await asyncio.Event().wait()

    native_cache.api.from_bluetooth_address_async.side_effect = pending_lookup
    task = asyncio.create_task(windows_discovery.cached_ring(ADDRESS))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancellation_after_acquiring_native_identity_still_closes(native_cache):
    class Native:
        bluetooth_address = ADDRESS_NUMBER
        close = Mock()

        @property
        def name(self):
            raise asyncio.CancelledError

    native = Native()
    native_cache.api.from_bluetooth_address_async.return_value = native

    with pytest.raises(asyncio.CancelledError):
        await windows_discovery.cached_ring(ADDRESS)
    native.close.assert_called_once_with()
