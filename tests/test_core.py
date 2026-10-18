from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from even_r1.ble import Transport, SERVICE, NOTIFY, BATTERY
from even_r1.settings import Settings
from even_r1.actions import Actions
from even_r1.protocol import Gesture

def test_settings_roundtrip(tmp_path):
    path=tmp_path/'settings.json'
    s=Settings(path); s.data['profile']='Media'; s.save()
    assert Settings(path).data['profile']=='Media'
    path.write_text('{')
    assert Settings(path).data['profile']=='Default'

def test_settings_validation(tmp_path):
    path=tmp_path/'settings.json'; path.write_text('{"scroll_steps":999,"auto_connect":"yes","profile":"missing"}')
    data=Settings(path).data
    assert data['scroll_steps']==20 and data['auto_connect'] is False and data['profile']=='Default'

def test_actions(tmp_path):
    class Input:
        def __init__(self): self.events=[]
        def press(self,k): self.events.append(('press',k))
        def release(self,k): self.events.append(('release',k))
        def scroll(self,x,y): self.events.append(('scroll',y))
    s=Settings(tmp_path/'s.json'); keyboard=Input(); mouse=Input()
    a=Actions(s,keyboard,mouse)
    assert a.execute(Gesture.TAP,1)=='Paused' and not keyboard.events
    a.enabled=True
    assert a.execute(Gesture.TAP,1)=='Play/pause'
    assert [x[0] for x in keyboard.events]==['press','release']
    assert a.execute(Gesture.TAP,1.01)=='Debounced'
    s.data['acceleration']=True
    a.execute(Gesture.FORWARD,2); a.execute(Gesture.FORWARD,2.2)
    assert mouse.events==[('scroll',-3),('scroll',-6)]
    with pytest.raises(ValueError): Actions.parse_hotkey('ctrl+bogus')

def test_release_after_input_error(tmp_path):
    class Broken:
        def __init__(self): self.pressed=[]; self.released=[]
        def press(self,k):
            if self.pressed: raise RuntimeError('injection failed')
            self.pressed.append(k)
        def release(self,k): self.released.append(k)
    s=Settings(tmp_path/'s.json')
    s.data['profiles']['Default'][Gesture.TAP]={'action':'Keyboard shortcut','hotkey':'ctrl+a'}
    keyboard=Broken(); a=Actions(s,keyboard,object()); a.enabled=True
    with pytest.raises(RuntimeError): a.execute(Gesture.TAP)
    assert keyboard.pressed==keyboard.released

def test_notification_dedup():
    events=[]; t=Transport(lambda k,v:events.append((k,v)))
    sender=SimpleNamespace(uuid=next(iter(NOTIFY)))
    raw=bytes.fromhex('0009610001000001000000')
    t.notification(sender,raw); t.notification(sender,raw)
    assert sum(k=='gesture' for k,v in events)==1
    assert sum(k=='packet' for k,v in events)==2

async def test_transport_no_writes(monkeypatch):
    calls=[]
    char=SimpleNamespace(uuid=next(iter(NOTIFY)),properties=['notify'])
    dfu=SimpleNamespace(uuid='0000fe59-0000-1000-8000-00805f9b34fb',properties=['write','notify'])
    class Services(list):
        def get_characteristic(self,uuid): return None
    class Client:
        def __init__(self,*args,**kwargs): self.services=Services([SimpleNamespace(uuid=SERVICE,characteristics=[char]),SimpleNamespace(uuid=dfu.uuid,characteristics=[dfu])])
        async def __aenter__(self): return self
        async def __aexit__(self,*args): calls.append('disconnect')
        async def start_notify(self,c,callback): calls.append(c.uuid); t.stop.set()
        async def write_gatt_char(self,*args): raise AssertionError('No writes allowed')
    monkeypatch.setattr('even_r1.ble.BleakClient',Client)
    t=Transport(lambda *args:None)
    await t.connect_once(object())
    assert calls==[char.uuid,'disconnect']


@pytest.fixture
def notification_client(monkeypatch):
    def install(denied):
        state=SimpleNamespace(attempts=[],callbacks=[],writes=[],pairings=[],closed=False)
        chars=[SimpleNamespace(uuid=f'bae800{suffix}-4f05-4503-8e65-3af1f7329d1f',properties=['notify']) for suffix in ('11','13')]
        class Services(list):
            def get_characteristic(self,uuid): return None
        class Client:
            def __init__(self,*args,**kwargs): self.services=Services([SimpleNamespace(uuid=SERVICE,characteristics=chars)])
            async def __aenter__(self): return self
            async def __aexit__(self,*args): state.closed=True
            async def start_notify(self,char,callback):
                state.attempts.append(char.uuid)
                if char.uuid in denied: raise OSError('The attribute requires authentication')
                state.callbacks.append((char,callback))
            async def write_gatt_char(self,*args):
                state.writes.append(args)
                raise AssertionError('No application writes allowed')
            async def pair(self,*args):
                state.pairings.append(args)
                raise AssertionError('No automatic pairing allowed')
        monkeypatch.setattr('even_r1.ble.BleakClient',Client)
        return state
    return install


@pytest.mark.parametrize('denied_suffix',['11','13'])
async def test_one_denied_notification_keeps_other_channel_listening(notification_client,denied_suffix):
    denied=f'bae800{denied_suffix}-4f05-4503-8e65-3af1f7329d1f'
    state=notification_client({denied})
    events=[]
    def emit(kind,value):
        events.append((kind,value))
        if (kind,value)==('status','Connected · listening'):
            char,callback=state.callbacks[0]
            callback(char,bytes.fromhex('ff0401'))
            transport.stop.set()
    transport=Transport(emit)
    await transport.connect_once(object())

    assert set(state.attempts)==NOTIFY
    assert len(state.callbacks)==1
    assert ('status','Connected · listening') in events
    assert any(kind=='gesture' and value.gesture==Gesture.TAP for kind,value in events)
    assert any(kind=='log' and denied in value and 'authentication' in value for kind,value in events)
    assert state.closed and not state.writes and not state.pairings


async def test_all_denied_notifications_never_report_connected(notification_client):
    state=notification_client(NOTIFY)
    events=[]
    transport=Transport(lambda kind,value:events.append((kind,value)))
    with pytest.raises(RuntimeError,match='No supported gesture notification subscriptions succeeded'):
        await transport.connect_once(object())

    assert set(state.attempts)==NOTIFY
    assert not state.callbacks
    assert not any(kind=='status' and value.startswith('Connected') for kind,value in events)
    assert sum(kind=='log' and 'authentication' in value for kind,value in events)==2
    assert state.closed and not state.writes and not state.pairings


async def test_discovery_filter(monkeypatch):
    data={'r':(SimpleNamespace(name='EVEN R1_test',address='1'),SimpleNamespace(local_name=None,rssi=-50,service_uuids=[])), 'x':(SimpleNamespace(name='Other',address='2'),SimpleNamespace(local_name=None,rssi=-10,service_uuids=[]))}
    monkeypatch.setattr('even_r1.ble.BleakScanner.discover',AsyncMock(return_value=data))
    assert len(await Transport(lambda *args:None).scan())==1
async def test_manual_stop_prevents_reconnect(monkeypatch):
    device=SimpleNamespace(address='AA')
    t=Transport(lambda *args:None)
    t.scan=AsyncMock(return_value=[(device,'EVEN R1',-55)])
    async def connected(d): t.stop.set()
    t.connect_once=AsyncMock(side_effect=connected)
    await t.run('AA')
    assert t.connect_once.await_count==1


async def test_selected_discovered_device_connects_without_rescan():
    selected=SimpleNamespace(address='AA:BB:CC:DD:EE:FF')
    transport=Transport(lambda *args:None)
    transport.scan=AsyncMock(side_effect=AssertionError('Selected device must not be scanned again'))
    async def connected(device): transport.stop.set()
    transport.connect_once=AsyncMock(side_effect=connected)

    await transport.run(selected.address.lower(),discovered_device=selected)

    transport.scan.assert_not_awaited()
    transport.connect_once.assert_awaited_once_with(selected)


async def test_mismatched_discovered_device_scans_for_requested_ring():
    wrong=SimpleNamespace(address='AA:BB:CC:DD:EE:01')
    requested=SimpleNamespace(address='AA:BB:CC:DD:EE:02')
    transport=Transport(lambda *args:None)
    transport.scan=AsyncMock(return_value=[(wrong,'EVEN R1_wrong',-50),(requested,'EVEN R1_requested',-55)])
    async def connected(device): transport.stop.set()
    transport.connect_once=AsyncMock(side_effect=connected)

    await transport.run(requested.address,reconnect=False,discovered_device=wrong)

    transport.scan.assert_awaited_once()
    transport.connect_once.assert_awaited_once_with(requested)


async def test_failed_connection_reports_unknown_battery(monkeypatch):
    events=[]; t=Transport(lambda k,v:events.append((k,v)))
    t.scan=AsyncMock(side_effect=RuntimeError('radio unavailable'))
    await t.run('AA',reconnect=False)
    assert ('battery',None) in events
    assert ('status','Connection unavailable') in events

async def test_saved_ring_uses_verified_windows_cache_when_scan_misses(monkeypatch):
    device=SimpleNamespace(address='E3:DB:87:0B:A7:2E')
    transport=Transport(lambda *args:None)
    transport.scan=AsyncMock(return_value=[])
    lookup=AsyncMock(return_value=device)
    monkeypatch.setattr('even_r1.ble.cached_ring',lookup)
    transport.connect_once=AsyncMock()
    await transport.run(device.address,reconnect=False)
    lookup.assert_awaited_once_with(device.address)
    transport.connect_once.assert_awaited_once_with(device)
