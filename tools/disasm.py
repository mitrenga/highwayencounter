#!/usr/bin/env python3
"""Rychlá disassembly kusu paměti z build/gameplay.z80 (pomůcka k M0/M6)."""
import sys, os
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,os.path.join(HERE,'vendor')); sys.path.insert(0,HERE)
from skoolkit.disassembler import Disassembler
from skoolkit.snapshot import Snapshot

class Cfg:
    asm_hex=True; asm_lower=False; defb_size=8; defm_size=66; defw_size=1
    handle_rst=False; opcodes=''; wrap=False
    class imaker:
        pass

def _imaker(address, operation, data, refs=()):
    class I: pass
    i=I(); i.address=address; i.operation=operation; i.bytes=data; i.sublengths=None
    i.comment=None; i.keep=None; i.refs=refs; i.nowarn=None
    return i
Cfg.imaker=staticmethod(lambda *a, **k: _imaker(*a, **k))

def load(path=None):
    sn=Snapshot.get(path or os.path.join(HERE,'..','build/gameplay.z80'))
    return [0]*16384+list(sn.ram(-1))

def dump(start, end, mem=None):
    mem=mem or load()
    d=Disassembler(mem, Cfg)
    for ins in d.disassemble(start, end, 'n'):
        print('$%04X  %-12s %s'%(ins.address,' '.join('%02X'%b for b in ins.bytes),ins.operation))

if __name__=='__main__':
    a=int(sys.argv[1],16); b=int(sys.argv[2],16)
    dump(a,b, load(sys.argv[3] if len(sys.argv)>3 else None))
