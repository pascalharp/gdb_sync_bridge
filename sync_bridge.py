#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# default values
HOST = 'localhost'
PORT = 8123
TIMEOUT = 5

import socket
import json
import gdb

registers = ["$r0", "$r1", "$r2", "$r3", "$r4", "$r5", "$r6", "$r7", "$r8", "$r9", "$r10", "$r11", "$r12", "$sp", "$lr", "$pc", "$cpsr"]

def save_regs():
    regs = {}
    for r in registers:
        regs[r] = str(gdb.parse_and_eval(r))
    return regs

def reduce_to_unmatched(regs_a, regs_b):
    unmatched = {}
    for k in regs_a:
        if regs_a[k] != regs_b[k]:
            unmatched[k] = (regs_a[k], regs_b[k])
    return unmatched

class Plugin(gdb.Command):

    def __init__(self):
        print("initializing sync bridge")
        gdb.Command.__init__(self, "sb_init", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.host = None
        self.port = None

    def invoke(self, arg, from_tty):
        # TODO parse args for custom host and port
        self.host = HOST
        self.port = PORT

        # register other commands
        cmds = [BridgeFollow(self), BridgeLead(self)]

        print("Registered {} commands".format(len(cmds)))

class BridgeFollow(gdb.Command):

    def __init__(self, plug):
        self.plug = plug
        gdb.Command.__init__(self, "sb_follow", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.sock = None

    def invoke(self, arg, from_tty):

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
            leader_regs = json.loads(self.sock.recv(1024).decode())
            regs = save_regs()
            self.sock.send(json.dumps(regs).encode())

            while leader_regs == regs:
                gdb.execute("si")
                leader_regs = json.loads(self.sock.recv(1024).decode())
                regs = save_regs()
                self.sock.send(json.dumps(regs).encode())

            print("Difference in regs detected")
            unmatched = reduce_to_unmatched(regs, leader_regs)
            print("<register> -> (Self, Leader)")
            for k in unmatched:
                (a, b) = unmatched[k]
                print("{} -> ( {} , {} )".format(k, a, b))

        except Exception as err:
            print("Error while bridge sync: {}".format(err))

        self.sock.close()
        self.sock = None

class BridgeLead(gdb.Command):

    def __init__(self, plug):
        self.plug = plug
        gdb.Command.__init__(self, "sb_lead", gdb.COMMAND_OBSCURE, gdb.COMPLETE_NONE)
        self.sock = None
        self.client_sock = None
        self.client_addr = None

    def invoke(self, arg, from_tty):

        print("Connecting to {} on port {} as leader".format(self.plug.host, self.plug.port))
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.plug.host, self.plug.port))
            self.sock.listen(1)
        except socket.error as err:
            if self.sock:
                self.sock.close()
                self.sock = None
            print("Connection error: {}".format(err))
            return None

        print("Waiting for follower...")
        (self.client_sock, self.client_addr) = self.sock.accept()
        print("Client connected")

        try:
            regs = save_regs()
            self.client_sock.send(json.dumps(regs).encode())
            follow_regs = json.loads(self.client_sock.recv(1024).decode())

            while regs == follow_regs:
                gdb.execute("si")
                regs = save_regs()
                self.client_sock.send(json.dumps(regs).encode())
                follow_regs = json.loads(self.client_sock.recv(1024).decode())

            print("Difference in regs detected")
            unmatched = reduce_to_unmatched(regs, follow_regs)
            print("<register> -> (Self, Follower)")
            for k in unmatched:
                (a, b) = unmatched[k]
                print("{} -> ( {} , {} )".format(k, a, b))

        except Exception as err:
            print("Error while bridge sync: {}".format(err))

        self.sock.close()
        self.sock = None

if __name__ == "__main__":
    try:
        id(SYNC_BRIDGE)
        print("Plugin already loaded")
    except:
        SYNC_BRIDGE = Plugin()
