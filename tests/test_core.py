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

async def test_failed_connection_reports_unknown_battery(monkeypatch):
    events=[]; t=Transport(lambda k,v:events.append((k,v)))
    t.scan=AsyncMock(side_effect=RuntimeError('radio unavailable'))
    await t.run('AA',reconnect=False)
    assert ('battery',None) in events
    assert ('status','Connection unavailable') in events
