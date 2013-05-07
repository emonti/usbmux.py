#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#    tcprelay.py - TCP connection relay for usbmuxd
#
# Copyright (C) 2009    Hector Martin "marcan" <hector@marcansoft.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 or version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import usbmux
import SocketServer
import select
from optparse import OptionParser
import sys
import threading

class SocketRelay(object):
    def __init__(self, a, b, maxbuf=65535):
        self.a = a
        self.b = b
        self.atob = ""
        self.btoa = ""
        self.maxbuf = maxbuf
    def handle(self):
        while True:
            rlist = []
            wlist = []
            xlist = [self.a, self.b]
            if self.atob:
                wlist.append(self.b)
            if self.btoa:
                wlist.append(self.a)
            if len(self.atob) < self.maxbuf:
                rlist.append(self.a)
            if len(self.btoa) < self.maxbuf:
                rlist.append(self.b)
            rlo, wlo, xlo = select.select(rlist, wlist, xlist)
            if xlo:
                return
            if self.a in wlo:
                n = self.a.send(self.btoa)
                self.btoa = self.btoa[n:]
            if self.b in wlo:
                n = self.b.send(self.atob)
                self.atob = self.atob[n:]
            if self.a in rlo:
                s = self.a.recv(self.maxbuf - len(self.atob))
                if not s:
                    return
                self.atob += s
            if self.b in rlo:
                s = self.b.recv(self.maxbuf - len(self.btoa))
                if not s:
                    return
                self.btoa += s
            #print "Relay iter: %8d atob, %8d btoa, lists: %r %r %r"%(len(self.atob), len(self.btoa), rlo, wlo, xlo)

class TCPRelay(SocketServer.BaseRequestHandler):
    def handle(self):
        print "Incoming connection to %d"%self.server.server_address[1]
        mux = usbmux.USBMux(options.sockpath)
        print "Discovering devices..."
        devcount = len(mux.devices)
        while True:
            mux.process(0.1)
            cnt = len(mux.devices)
            if cnt > devcount:
                devcount = cnt
            else:
                break

        if not mux.devices:
            print "No devices found"
            self.request.close()
            return

        # select a device
        dev=None
        if self.server.device:
            for d in mux.devices:
                if d.serial == self.server.device:
                    dev = d
                    break

            if not dev:
                print "Unable to find device: %s" % self.server.device
                self.request.close()
                return
        else:
            dev = mux.devices[0]

        print "Connecting to device %s"%str(dev)
        dsock = mux.connect(dev, self.server.rport)
        lsock = self.request
        print "Connection established, relaying data"
        try:
            fwd = SocketRelay(dsock, lsock, self.server.bufsize * 1024)
            fwd.handle()
        finally:
            dsock.close()
            lsock.close()
        print "Connection closed"

class TCPServer(SocketServer.TCPServer):
    allow_reuse_address = True
    device = None

class ThreadedTCPServer(SocketServer.ThreadingMixIn, TCPServer):
    pass

def do_list():
    mux = usbmux.USBMux()
    print "Listing devices..."
    devcount = len(mux.devices)
    while True:
        mux.process(0.1)
        cnt = len(mux.devices)
        if cnt > devcount:
            devcount = cnt
        else:
            break
    for dev in mux.devices:
        print dev


HOST = "localhost"

parser = OptionParser(usage="usage: %prog [OPTIONS] RemotePort[:LocalPort][-UDID] [RemotePort[:LocalPort][-UDID]...")
parser.add_option("-t", "--threaded", dest='threaded', action='store_true', default=False, help="use threading to handle multiple connections at once")
parser.add_option("-l", "--list", dest='list', action='store_true', default=False, help="list attached devices")
parser.add_option("-b", "--bufsize", dest='bufsize', action='store', metavar='KILOBYTES', type='int', default=128, help="specify buffer size for socket forwarding")
parser.add_option("-s", "--socket", dest='sockpath', action='store', metavar='PATH', type='str', default=None, help="specify the path of the usbmuxd socket")
parser.add_option("-c", "--config", dest='config', action='store', metavar='CONFIG', type='str', default=None, help="specify config file for relays")

options, args = parser.parse_args()

serverclass = TCPServer
if options.threaded:
    serverclass = ThreadedTCPServer

if options.list:
    do_list()
    sys.exit(0)

if options.config:
    f = open(options.config)
    args += f.readlines()
    f.close

if len(args) == 0:
    parser.print_help()
    sys.exit(1)

ports = []


for arg in args:
    arg = arg.rstrip("\n")
    try:
        dev = None
        if '-' in arg:
            arg, dev = arg.split('-')

        if ':' in arg:
            rport, lport = arg.split(":")
            rport = int(rport)
            lport = int(lport)
            ports.append((rport, lport, dev))
        else:
            ports.append((int(arg), int(arg)))
    except:
        parser.print_help()
        sys.exit(1)

servers=[]

for rport, lport, dev in ports:
    print "Forwarding local port %d to remote port %d on device %s"%(lport, rport, dev)
    server = serverclass((HOST, lport), TCPRelay)
    server.rport = rport
    server.device = dev
    server.bufsize = options.bufsize
    servers.append(server)

alive = True

while alive:
    try:
        rl, wl, xl = select.select(servers, [], [])
        for server in rl:
            server.handle_request()
    except:
        alive = False
