#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# default values
HOST = 'localhost'
PORT = 8123
TIMEOUT = 5

import socket
import gdb

registers = ["$r0", "$r1", "$r2", "$r3", "$r4", "$r5", "$r6", "$r7", "$r8", "$r9", "$r10", "$r11", "$r12", "$sp", "$lr", "$pc", "$cpsr"]

def save_regs():
    regs = {}
    for r in registers:
        print(r)
        regs[r] = str(gdb.parse_and_eval(r)).encode()
        print(regs[r])
    print(regs)
    return regs

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
            prev_pc = "Unknown"
            leader_pc = self.sock.recv(1024).decode()
            pc = str(gdb.parse_and_eval("$pc"))
            self.sock.send(leader_pc.encode())
            print("Own pc {}, leader pc {}".format(pc, leader_pc))

            while leader_pc == pc:
                gdb.execute("si")
                prev_pc = pc
                leader_pc = self.sock.recv(1024).decode()
                pc = str(gdb.parse_and_eval("$pc"))
                self.sock.send(pc.encode())

            print("Leader pc {} did not match own pc {}".format(leader_pc, pc))
            print("Last matching pc {}".format(prev_pc))

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
            prev_pc = "Unknown"
            pc = str(gdb.parse_and_eval("$pc"))
            self.client_sock.send(pc.encode())
            follow_pc = self.client_sock.recv(1024).decode()
            print("Own pc {}, follow pc {}".format(pc, follow_pc))
            while follow_pc == pc:
                gdb.execute("si")
                prev_pc = pc
                pc = str(gdb.parse_and_eval("$pc"))
                self.client_sock.send(pc.encode())
                follow_pc = self.client_sock.recv(1024).decode()

            print("Follow pc {} did not match own pc {}".format(follow_pc, pc))
            print("Last matching pc {}".format(prev_pc))

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
