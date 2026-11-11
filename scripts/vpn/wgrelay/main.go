// wgrelay: cliente WireGuard en espacio de usuario para probar la VPN de
// PoorSDR4All sin móvil (lo usa scripts/bench_remoto.py --vpn).
//
// Se conecta al túnel como lo haría el móvil y abre en 127.0.0.1 puertos que
// entran por él:
//
//	-tcp L:R  conexiones a 127.0.0.1:L van a <server-ip>:R por el túnel
//	-udp L:R  datagramas a <bind>:L van a <server-ip>:R (y las respuestas vuelven)
//
// Escribe "ready" al estar listo y sale al cerrarse stdin.
package main

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"sync"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"
	"golang.zx2c4.com/wireguard/tun/netstack"
)

type pairs []string

func (p *pairs) String() string     { return strings.Join(*p, ",") }
func (p *pairs) Set(v string) error { *p = append(*p, v); return nil }

func hexKey(b64 string) string {
	b, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		fatal("clave inválida: %v", err)
	}
	return hex.EncodeToString(b)
}

func fatal(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "wgrelay: "+f+"\n", a...)
	os.Exit(1)
}

func ports(p string) (int, int) {
	l, r, ok := strings.Cut(p, ":")
	lp, e1 := strconv.Atoi(l)
	rp, e2 := strconv.Atoi(r)
	if !ok || e1 != nil || e2 != nil {
		fatal("par de puertos inválido: %s", p)
	}
	return lp, rp
}

func main() {
	priv := flag.String("priv", "", "clave privada del cliente (base64)")
	serverPub := flag.String("server-pub", "", "clave pública del servidor (base64)")
	endpoint := flag.String("endpoint", "127.0.0.1:51821", "servidor WireGuard")
	ip := flag.String("ip", "10.9.0.2", "IP del cliente en el túnel")
	serverIP := flag.String("server-ip", "10.9.0.1", "IP del servidor en el túnel")
	bind := flag.String("bind", "127.0.0.1", "IP local en la que escuchan los -udp")
	var tcp, udp pairs
	flag.Var(&tcp, "tcp", "L:R (repetible)")
	flag.Var(&udp, "udp", "L:R (repetible)")
	flag.Parse()

	tdev, tnet, err := netstack.CreateNetTUN([]netip.Addr{netip.MustParseAddr(*ip)}, nil, 1380)
	if err != nil {
		fatal("%v", err)
	}
	dev := device.NewDevice(tdev, conn.NewDefaultBind(), &device.Logger{Verbosef: device.DiscardLogf, Errorf: device.DiscardLogf})
	cfg := fmt.Sprintf("private_key=%s\npublic_key=%s\nendpoint=%s\nallowed_ip=%s/32\npersistent_keepalive_interval=25\n",
		hexKey(*priv), hexKey(*serverPub), *endpoint, *serverIP)
	if err := dev.IpcSet(cfg); err != nil {
		fatal("%v", err)
	}
	if err := dev.Up(); err != nil {
		fatal("%v", err)
	}
	server := netip.MustParseAddr(*serverIP)

	for _, p := range tcp {
		lp, rp := ports(p)
		ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", lp))
		if err != nil {
			fatal("%v", err)
		}
		go func(ln net.Listener, rp int) {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go func(c net.Conn) {
					defer c.Close()
					r, err := tnet.DialContextTCPAddrPort(context.Background(), netip.AddrPortFrom(server, uint16(rp)))
					if err != nil {
						return
					}
					defer r.Close()
					var wg sync.WaitGroup
					wg.Add(2)
					go func() { io.Copy(r, c); r.CloseWrite(); wg.Done() }()
					go func() { io.Copy(c, r); wg.Done() }()
					wg.Wait()
				}(c)
			}
		}(ln, rp)
	}

	for _, p := range udp {
		lp, rp := ports(p)
		local, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP(*bind), Port: lp})
		if err != nil {
			fatal("%v", err)
		}
		remote, err := tnet.DialUDPAddrPort(netip.AddrPort{}, netip.AddrPortFrom(server, uint16(rp)))
		if err != nil {
			fatal("%v", err)
		}
		var mu sync.Mutex
		var client *net.UDPAddr
		go func() {
			buf := make([]byte, 65535)
			for {
				n, from, err := local.ReadFromUDP(buf)
				if err != nil {
					return
				}
				mu.Lock()
				client = from
				mu.Unlock()
				remote.Write(buf[:n])
			}
		}()
		go func() {
			buf := make([]byte, 65535)
			for {
				n, err := remote.Read(buf)
				if err != nil {
					return
				}
				mu.Lock()
				to := client
				mu.Unlock()
				if to != nil {
					local.WriteToUDP(buf[:n], to)
				}
			}
		}()
	}

	fmt.Println("ready")
	io.Copy(io.Discard, os.Stdin)
	dev.Close()
}
