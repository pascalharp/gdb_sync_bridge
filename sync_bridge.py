#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# default values
HOST = 'localhost'
PORT = 8123
TIMEOUT = 5

import argparse
import socket
import json
import gdb

from typing import Tuple, List, Dict

def sb_print(val: str):
    print("\033[93m[\033[01mSync Bridge]\033[00m {}" .format(val))

def get_reg_values(regs: List[gdb.RegisterDescriptor]) -> List[Tuple[str, int]]:
    """
    Returns a list of tuples with the corresponding register and its values
    """
    loaded = []
    frame = gdb.selected_frame()
    for r in regs:
        loaded.append( (r.name, int(frame.read_register(r)) & 0xffffffff) ) # hack for unsigned int 32 bit
    return loaded

def encode_reg_values(rv) -> str:
    """
    Encodes the list of tuples returned from get_reg_values to a json string.
    Format:
    [
        {
            reg: "r0",
            val: 1234
        },
        ...
    ]
    """
    vals = list(map(lambda x: {"reg": x[0], "val": x[1]}, rv ))
    return json.dumps(vals)

def decode_reg_values(js: str) -> List[Tuple[str, int]]:
    """
    Reverse of encode_reg_values.
    """
    vals = json.loads(js)
    return list(map(lambda x: (x["reg"], x["val"]), vals ))

def reduce_to_unmatched(
        regs_a: List[Tuple[str, int]],
        regs_b: List[Tuple[str, int]]
    ) -> Dict[str, Tuple[int, int]]:

    missmatch = {}
    ra = dict(regs_a)
    rb = dict(regs_b)

    for k in ra:
        va = ra[k]
        vb = rb[k]
        if va != vb:
            missmatch[k] = (va, vb)

    return missmatch

def skip_over(end: int):
    """ Set a temporary breakpoint and continue till then """
    sb_print("Skipping checks and continuing till {}".format(hex(end)))
    gdb.execute("tbreak *{}".format(hex(end)))
    gdb.execute("continue")
    pass

class Plugin(gdb.Command):

    def __init__(self):
        print("initializing sync bridge")
        gdb.Command.__init__(self, "sb_init", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.host = None
        self.port = None
        self.all_registers = []

    def invoke(self, args, tty):
        # TODO parse args for custom host and port
        self.host = HOST
        self.port = PORT

        # load available registers. This has to be done after target remote
        # TODO make customizable
        frame = gdb.selected_frame()
        arch = frame.architecture()
        self.all_registers = list(arch.registers())

        # register other commands
        cmds = [BridgeFollow(self), BridgeLead(self)]

        sb_print("Loaded. Registered {} commands".format(len(cmds)))

class BridgeFollow(gdb.Command):

    def __init__(self, plug):
        self.plug = plug
        gdb.Command.__init__(self, "sb_follow", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.sock = None
        self.regs = []
        self.skip_over: Dict[int, int] = {}

    def invoke(self, args, tty):

        print("Connecting to {} on port {} as follower".format(self.plug.host, self.plug.port))
        try:
            self.sock = socket.create_connection((self.plug.host, self.plug.port), TIMEOUT)
        except socket.error as err:
            if self.sock:
                self.sock.close()
                self.sock = None
            print("Connection error: {}".format(err))
            return None

        try:
            sb_print("Exchanging compatible registers")
            # wait for leader regs sync
            leader_regs = json.loads(self.sock.recv(1024 * 4).decode())
            for r in self.plug.all_registers:
                if r.name in leader_regs:
                    self.regs.append(r)

            # reply with matching list
            self.sock.send(json.dumps(list(map(lambda x: x.name, self.regs))).encode())

            sb_print("Register list: {}".format(list(map(lambda x: x.name, self.regs))))

            sb_print("Waiting for skip list from leader")
            self.skip_over = dict(map(lambda x: (x["start"], x["end"]), json.loads(self.sock.recv(1024).decode())))

            sb_print("Starting single step synchronization")
            missmatch: Dict[str, Tuple[int, int]] = {}
            while True:
                pc = int(gdb.selected_frame().read_register("pc"))
                if pc in self.skip_over:
                    skip_over(self.skip_over[pc])

                # wait for leader regs over socket
                leader_regs = decode_reg_values(self.sock.recv(1024).decode())
                # load own regs and send to leader
                self_regs = get_reg_values(self.regs)
                self.sock.send(encode_reg_values(self_regs).encode())
                # compare
                missmatch = reduce_to_unmatched(self_regs, leader_regs)

                if len(missmatch) > 0:
                    break

                gdb.execute("stepi")

            sb_print("### Difference detected ###")
            sb_print("<register> -> (Self, Leader)")
            for k in missmatch:
                (a, b) = missmatch[k]
                print("{} -> ( {} , {} )".format(k, hex(a), hex(b)))

        except Exception as err:
            sb_print("Error while bridge sync: {}".format(err))

        self.sock.close()
        self.sock = None

class BridgeLead(gdb.Command):

    def __init__(self, plug):
        self.plug = plug
        gdb.Command.__init__(self, "sb_lead", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.sock = None
        self.client_sock = None
        self.client_addr = None
        self.regs = []
        self.skip_over: Dict[int, int] = {}

    def invoke(self, args, tty):

        parser = argparse.ArgumentParser()
        parser.add_argument('--skip', dest="skip", action="append", default=[])

        args = parser.parse_args(args.split())

        for arg in args.skip:
            skip = arg.split(':')
            if len(skip) < 2:
                raise Exception("{} - Invalid format for --skip".format(arg))
            self.skip_over[int(skip[0], 0)] = int(skip[1], 0)

        sb_print("Connecting to {} on port {} as leader".format(self.plug.host, self.plug.port))
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.plug.host, self.plug.port))
            self.sock.listen(1)
        except socket.error as err:
            if self.sock:
                self.sock.close()
                self.sock = None
            sb_print("Connection error: {}".format(err))
            return None

        sb_print("Waiting for follower...")
        (self.client_sock, self.client_addr) = self.sock.accept()
        sb_print("Client connected")

        try:
            sb_print("Exchanging compatible registers")
            # send regs to follower to sync
            self.client_sock.send(json.dumps(list(map(lambda x: x.name, self.plug.all_registers))).encode())

            # wait for follower regs sync
            follow_regs = json.loads(self.client_sock.recv(1024 * 4).decode())
            for r in self.plug.all_registers:
                if r.name in follow_regs:
                    self.regs.append(r)

            sb_print("Register list: {}".format(list(map(lambda x: x.name, self.regs))))

            sb_print("Sending addresses to skip to follower")
            self.client_sock.send(json.dumps(list(map(lambda d: {"start": d[0], "end": d[1]}, self.skip_over.items()))).encode())

            sb_print("Starting single step synchronization")
            missmatch: Dict[str, Tuple[int, int]] = {}
            while True:
                pc = int(gdb.selected_frame().read_register("pc"))
                if pc in self.skip_over:
                    skip_over(self.skip_over[pc])

                # load current own registers and send to follower
                self_regs = get_reg_values(self.regs)
                self.client_sock.send(encode_reg_values(self_regs).encode())
                # wait for follower regs
                follow_regs = decode_reg_values(self.client_sock.recv(1024).decode())
                # compare
                missmatch = reduce_to_unmatched(self_regs, follow_regs)

                if len(missmatch) > 0:
                    break

                gdb.execute("stepi")

            sb_print("### Difference detected ###")
            sb_print("<register> -> (Self, Follower)")
            for k in missmatch:
                (a, b) = missmatch[k]
                sb_print("{} -> ( {} , {} )".format(k, hex(a), hex(b)))

        except Exception as err:
            sb_print("Error while bridge sync: {}".format(err))

        self.sock.close()
        self.sock = None

if __name__ == "__main__":
    try:
        id(SYNC_BRIDGE)
        sb_print("Plugin already loaded")
    except:
        SYNC_BRIDGE = Plugin()
