import pytest
from even_r1.protocol import decode, Gesture

@pytest.mark.parametrize('raw,expected', [('ff0401',Gesture.TAP),('ff0402',Gesture.DOUBLE),('ff0320',Gesture.HOLD),('ff0500',Gesture.FORWARD),('ff0501',Gesture.FORWARD), *[(f'ff05{x:02x}',Gesture.BACKWARD) for x in range(2,256)]])
def test_direct(raw, expected): assert decode(bytes.fromhex(raw)).gesture == expected

@pytest.mark.parametrize('code,expected', [(0,Gesture.HOLD),(1,Gesture.TAP),(2,Gesture.DOUBLE),(4,Gesture.BACKWARD),(5,Gesture.FORWARD),(8,Gesture.RELEASE)])
def test_charger(code, expected):
    event = decode(bytes([0,9,0x61,0,code,0x34,0x12,0xff,0xff,0xff,0xff]))
    assert (event.gesture,event.parameter,event.tick) == (expected,0x1234,0xffffffff)

@pytest.mark.parametrize('raw', [b'',b'\xff',b'\xff\x04',b'\xff\x04\x00',b'\xff\x03\x21',b'\xff\x04\x01\x00',bytes.fromhex('0009610003000000000000'),bytes.fromhex('0109610001000000000000')])
def test_unknown(raw): assert decode(raw) is None

def test_truncations():
    raw=bytes.fromhex('0009610001000000000000')
    for n in range(11): assert decode(raw[:n]) is None
    assert decode(raw+b'\x00') is None
