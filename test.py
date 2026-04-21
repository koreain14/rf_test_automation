import pyvisa

def test_idn(resource_name: str):
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(resource_name)
    inst.timeout = 5000
    inst.write_termination = '\n'
    inst.read_termination = '\n'

    try:
        ans = inst.query("*IDN?")
        print("IDN OK:", repr(ans))
    finally:
        inst.close()

test_idn("TCPIP0::192.168.1.77::5025::SOCKET")